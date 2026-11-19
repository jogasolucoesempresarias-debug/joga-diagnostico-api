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

from . import models, scoring, relatorio_ia, prebrief, estoque_scoring, estoque_ia
from .admin import router as admin_router
from .blog import public_router as blog_router, admin_router as blog_admin_router
from .config import config
from .database import get_db, init_db, migrate_db
from .schemas import SubmitBody, SubmitEstoqueBody

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
app.include_router(blog_router)
app.include_router(blog_admin_router)


@app.get("/api/diagnostico/health")
async def health():
    return {"status": "ok"}


@app.get("/admin")
async def admin_atalho():
    """Atalho curto para o painel de admin."""
    return RedirectResponse(url="/api/diagnostico/admin")


@app.get("/admin/blog")
async def blog_admin_atalho():
    """Endereço curto que o João usa para escrever no blog."""
    return RedirectResponse(url="/api/blog/admin")


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


# Texto das perguntas e1..e12 — precisa bater com o que a LP mostra (lib/lp-estoque.ts).
# Fica aqui porque a IA cita as respostas quase literalmente: sem o enunciado, ela inventa.
PERGUNTAS_ESTOQUE = {
    "e1": "Você sabe quanto dinheiro está parado em estoque acima da necessidade?",
    "e2": "Sua empresa identifica rapidamente produtos há muitos dias sem venda?",
    "e3": "Você acompanha o percentual de ruptura do estoque?",
    "e4": "A ruptura é acompanhada por comprador e por curva ABC?",
    "e5": "Sua equipe identifica antecipadamente produtos próximos do vencimento?",
    "e6": "Você sabe quanto perdeu por vencimento nos últimos 12 meses?",
    "e7": "Seus compradores trabalham com cobertura-alvo definida?",
    "e8": "O lead time real dos fornecedores é acompanhado?",
    "e9": "Sua empresa tem orçamento estruturado de compras?",
    "e10": "Existe sugestão de compras baseada em parâmetros definidos pela empresa?",
    "e11": "Os responsáveis recebem automaticamente os relatórios e alertas do estoque?",
    "e12": "Cada comprador tem meta de ruptura e de compras acompanhada individualmente?",
}


def _analise_markdown(analise: dict) -> str:
    """A coluna `relatorio` é Text e o e-mail da equipe renderiza markdown — converte a
    análise estruturada para o mesmo formato, sem duplicar geração por IA."""
    partes = [analise.get("leitura", "")]
    for p in analise.get("pontos", []):
        partes.append(f"### {p.get('titulo', '')}\n{p.get('texto', '')}")
    if analise.get("fecho"):
        partes.append(f"**Por onde começar:** {analise['fecho']}")
    return "\n\n".join(x for x in partes if x)


@app.post("/api/diagnostico/estoque")
async def submit_estoque(
    body: SubmitEstoqueBody, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Questionário da LP de Gestão de Estoque.

    Diferenças em relação ao /submit geral:
      • placar próprio (5 áreas de estoque, não as 5 do negócio) — estoque_scoring;
      • a análise da IA é escrita PARA o cliente e devolvida na resposta (ele lê na tela
        assim que deixa o contato) — estoque_ia, sem nenhuma cifra;
      • o lead cai na MESMA tabela e no MESMO admin, marcado com origem='lp-estoque';
      • dispara só para a equipe JOGA (WhatsApp + e-mail). O cliente NÃO recebe envio:
        o que ele queria já apareceu na tela.
    """
    try:
        contato = body.contato()

        resultado = estoque_scoring.calcular(body.respostas)
        # O questionário de estoque não tem campo aberto de dor: sintetiza do placar para o
        # pré-brief não sair com "(não declarada)".
        contato["desafio"] = estoque_scoring.desafio_sintetico(resultado)

        analise = estoque_ia.gerar(contato, body.respostas, PERGUNTAS_ESTOQUE, resultado)

        registro = models.salvar(
            db,
            contato=contato,
            respostas=body.respostas,
            placar=resultado["placar"],
            relatorio=_analise_markdown(analise),
            origem="lp-estoque",
            analise=analise,
        )

        # Só equipe (WhatsApp + e-mail). Sem enviar_aviso_cliente aqui, de propósito: o que
        # o cliente queria já apareceu na tela dele.
        background.add_task(
            prebrief.enviar_equipe,
            contato,
            resultado,
            _analise_markdown(analise),
            False,
            prebrief.montar_texto_estoque(contato, resultado),
            f"[Estoque] {contato.get('empresa')} — {resultado['maior_dor']['area']}",
        )

        return {
            "id": registro.id,
            "placar": resultado["placar"],
            "resumo": resultado["resumo"],
            "oportunidades": [o["titulo"] for o in resultado["oportunidades"]],
            "analise": analise,
        }

    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro no /estoque: {e}")
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
