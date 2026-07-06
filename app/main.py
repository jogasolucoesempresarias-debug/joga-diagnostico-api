"""
Diagnóstico JOGA — API (FastAPI). Fase 2a: questionário → placar → relatório IA → pré-brief.

Rotas sob /api/diagnostico (espelha o roteamento Traefik: sem strip de prefixo).
Mesma origem em produção; CORS liberado só para dev (front Next em :3000).
"""
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from . import models, scoring, relatorio_ia, prebrief
from .admin import router as admin_router
from .config import config
from .database import get_db, init_db, migrate_db
from .schemas import SubmitBody

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
MODELO_PATH = os.path.join(TEMPLATES_DIR, "modelo_diagnostico.xlsx")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro ao inicializar banco: {e}")
    try:
        migrate_db()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro ao migrar banco: {e}")
    yield


app = FastAPI(title="Diagnóstico JOGA API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)


@app.get("/api/diagnostico/health")
async def health():
    return {"status": "ok"}


@app.get("/admin")
async def admin_atalho():
    """Atalho curto para o painel de admin."""
    return RedirectResponse(url="/api/diagnostico/admin")


@app.post("/api/diagnostico/submit")
async def submit(body: SubmitBody, background: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Recebe o questionário: calcula o placar, gera o relatório por IA, salva o lead
    e agenda (background) o pré-brief pro João + o relatório completo pro lead.
    Retorna o resultado PARCIAL (placar + títulos das oportunidades). Sem cifras.
    """
    try:
        contato = body.contato()

        resultado = scoring.calcular(body.respostas, contato.get("setor"))
        relatorio = relatorio_ia.gerar(contato, body.respostas, resultado)

        registro = models.salvar(
            db,
            contato=contato,
            respostas=body.respostas,
            placar=resultado["placar"],
            relatorio=relatorio,
        )

        # Envios fora do caminho crítico da resposta.
        # 1) equipe JOGA: e-mail único (pré-brief + relatório) + WhatsApp (pré-brief).
        # 2) cliente: e-mail curto de "recebido" (gated por AVISO_CLIENTE_ATIVO; sem WhatsApp).
        background.add_task(prebrief.enviar_equipe, contato, resultado, relatorio, False)
        background.add_task(prebrief.enviar_aviso_cliente, contato, resultado)

        return {
            "id": registro.id,
            "placar": resultado["placar"],
            "oportunidades": [o["titulo"] for o in resultado["oportunidades"]],
            "mensagem": "Recebemos seu diagnóstico. A JOGA entra em contato em até 48h.",
        }

    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro no /submit: {e}")
        return JSONResponse({"erro": str(e)}, status_code=500)


@app.post("/api/diagnostico/upload")
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    diagnostico_id: int = Form(...),
    mapeamento: str = Form(None),
    db: Session = Depends(get_db),
):
    """
    Fase 2b — recebe o export cru (xlsx/csv), lê as colunas (3 camadas) e devolve os achados,
    OU pede confirmação do mapeamento. LGPD: analisa em memória, NÃO grava o arquivo.
    """
    try:
        from .planilha import leitor  # import tardio (pandas) — não pesa o /submit

        conteudo = await file.read()  # em memória, descartado ao fim da request
        mapa = json.loads(mapeamento) if mapeamento else None
        resultado = leitor.ler(conteudo, file.filename, mapeamento_confirmado=mapa)

        # Só persiste quando há achados de fato (não na etapa de confirmação).
        if resultado.get("ok") and resultado.get("achados", {}).get("ok"):
            models.atualizar_achados(db, diagnostico_id, resultado["achados"])
            # Avisa a equipe JOGA dos achados reais da planilha.
            reg = db.query(models.Diagnostico).filter(models.Diagnostico.id == diagnostico_id).first()
            if reg:
                contato = {"nome": reg.nome, "empresa": reg.empresa, "whatsapp": reg.whatsapp, "email": reg.email}
                background.add_task(prebrief.enviar_achados_equipe, contato, resultado["achados"])

        return resultado
    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro no /upload: {e}")
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


@app.get("/api/diagnostico/modelo")
async def modelo():
    """Baixa a planilha-modelo (fallback camada 3)."""
    if not os.path.exists(MODELO_PATH):
        return JSONResponse({"erro": "Modelo indisponível."}, status_code=404)
    return FileResponse(
        MODELO_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="modelo_diagnostico_joga.xlsx",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
