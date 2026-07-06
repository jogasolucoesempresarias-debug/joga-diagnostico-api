"""
Painel de admin do Diagnóstico JOGA — lista de leads + detalhe (relatório, pré-brief, achados).

Pensado para escalar: busca, filtros (setor/urgência/planilha), stats e paginação.
Protegido por token (config.ADMIN_TOKEN) enviado pelo front no header/na query.
A página HTML é pública (só o shell de login); os dados exigem token.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import scoring, prebrief
from .config import config
from .database import get_db
from .models import Diagnostico

router = APIRouter(prefix="/api/diagnostico/admin", tags=["admin"])

ADMIN_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "admin.html"
)


def _auth(token: str):
    if not config.ADMIN_TOKEN or token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Não autorizado")


@router.get("")
async def pagina():
    """Serve a página HTML do admin (login + dashboard)."""
    return FileResponse(ADMIN_HTML, media_type="text/html")


@router.get("/api/leads")
def listar(
    token: str = Query(...),
    q: str = Query(None),
    setor: str = Query(None),
    urgencia: str = Query(None),
    tem_planilha: bool = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _auth(token)

    base = db.query(Diagnostico)
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Diagnostico.nome.ilike(like), Diagnostico.empresa.ilike(like)))
    if setor:
        base = base.filter(Diagnostico.setor == setor)
    if urgencia:
        base = base.filter(Diagnostico.urgencia == urgencia)
    if tem_planilha is not None:
        base = base.filter(Diagnostico.tem_planilha == tem_planilha)

    total = base.count()
    rows = base.order_by(Diagnostico.id.desc()).offset(offset).limit(limit).all()

    # Stats sobre a base inteira (não a filtrada).
    geral = db.query(Diagnostico)
    stats = {
        "total": geral.count(),
        "pra_ontem": geral.filter(Diagnostico.urgencia == "pra_ontem").count(),
        "com_planilha": geral.filter(Diagnostico.tem_planilha.is_(True)).count(),
        "por_setor": dict(
            db.query(Diagnostico.setor, func.count(Diagnostico.id)).group_by(Diagnostico.setor).all()
        ),
    }

    leads = [{
        "id": r.id,
        "criado_em": r.criado_em.isoformat() if r.criado_em else None,
        "nome": r.nome,
        "empresa": r.empresa,
        "setor": r.setor,
        "faturamento": r.faturamento,
        "urgencia": r.urgencia,
        "tem_planilha": bool(r.tem_planilha),
        "placar": r.placar or {},
    } for r in rows]

    return {"total": total, "stats": stats, "limit": limit, "offset": offset, "leads": leads}


@router.get("/api/leads/{lead_id}")
def detalhe(lead_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    _auth(token)
    r = db.query(Diagnostico).filter(Diagnostico.id == lead_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    contato = {
        "nome": r.nome, "empresa": r.empresa, "cargo": r.cargo,
        "whatsapp": r.whatsapp, "email": r.email, "setor": r.setor,
        "erp": r.erp, "faturamento": r.faturamento, "colaboradores": r.colaboradores,
        "desafio": r.desafio, "urgencia": r.urgencia,
    }
    resultado = scoring.calcular(r.respostas or {}, r.setor)
    prebrief_txt = prebrief.montar_texto(contato, resultado, tem_planilha=bool(r.tem_planilha))

    return {
        "id": r.id,
        "criado_em": r.criado_em.isoformat() if r.criado_em else None,
        "contato": contato,
        "placar": r.placar or {},
        "oportunidades": [o["titulo"] for o in resultado.get("oportunidades", [])],
        "relatorio": r.relatorio or "",
        "prebrief": prebrief_txt,
        "tem_planilha": bool(r.tem_planilha),
        "achados": r.achados or None,
    }
