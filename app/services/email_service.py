"""
Serviço de e-mail via Resend — reusa o padrão já em produção na JOGA
(Multpel HTML/server.py e DanfeZap/app/services/email_service.py).

Remetente: config.RESEND_FROM = joga@jogasolucoes.com.br (domínio já verificado).
Helper genérico: enviar(destinatarios, assunto, html, cc=None, attachments=None).
Contrato: {"sucesso": bool, "erro": str|None}.
"""
import base64
import logging
from typing import List, Optional

import resend

from ..config import config

logger = logging.getLogger(__name__)

# Configura a API Key uma vez, no import (igual DanfeZap/Multpel).
resend.api_key = config.RESEND_API_KEY


def enviar(
    destinatarios: List[str],
    assunto: str,
    html: str,
    cc: Optional[List[str]] = None,
    attachments: Optional[List[dict]] = None,
) -> dict:
    """
    Envia um e-mail. `attachments` = lista de tuplas (filename, bytes) OU dicts
    já no formato Resend {"filename","content"(base64)}.
    """
    try:
        if not resend.api_key:
            logger.error("RESEND_API_KEY não configurada")
            return {"sucesso": False, "erro": "API Key não configurada"}

        payload = {
            "from": config.RESEND_FROM,
            "to": destinatarios,
            "subject": assunto,
            "html": html,
        }
        if cc:
            payload["cc"] = cc
        if attachments:
            payload["attachments"] = [_normalizar_anexo(a) for a in attachments]

        resend.Emails.send(payload)
        logger.info(f"E-mail enviado para {destinatarios} (assunto: {assunto})")
        return {"sucesso": True, "erro": None}

    except Exception as e:  # noqa: BLE001
        logger.error(f"Erro ao enviar e-mail: {e}")
        return {"sucesso": False, "erro": str(e)}


def _normalizar_anexo(anexo) -> dict:
    if isinstance(anexo, dict):
        return anexo
    filename, conteudo = anexo
    if isinstance(conteudo, (bytes, bytearray)):
        conteudo = base64.b64encode(conteudo).decode("utf-8")
    return {"filename": filename, "content": conteudo}
