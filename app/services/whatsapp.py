"""
Serviço de WhatsApp via UazAPI — copiado de DanfeZap (services/whatsapp.py).
Só o essencial da Fase 2a: enviar_mensagem(telefone, texto).
Contrato: retorna {"sucesso": bool, "erro": str|None}.
"""
import httpx
import logging
from ..config import config
from ..utils.telefone import normalizar_telefone_br

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(self):
        self.base_url = config.UAZAPI_URL
        self.token = config.UAZAPI_TOKEN
        self.timeout = 30.0

    def _get_headers(self) -> dict:
        return {"Content-Type": "application/json", "token": self.token}

    def _formatar_numero(self, telefone: str) -> str:
        return normalizar_telefone_br(telefone)

    async def enviar_mensagem(self, telefone: str, texto: str) -> dict:
        try:
            url = f"{self.base_url}/send/text"
            payload = {"number": self._formatar_numero(telefone), "text": texto}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=self._get_headers())

            if response.status_code in (200, 201):
                return {"sucesso": True, "erro": None}
            logger.error(f"Erro enviar_mensagem: {response.status_code} - {response.text}")
            return {"sucesso": False, "erro": f"Status {response.status_code}: {response.text}"}

        except httpx.TimeoutException:
            return {"sucesso": False, "erro": "Timeout ao enviar mensagem"}
        except Exception as e:  # noqa: BLE001
            return {"sucesso": False, "erro": str(e)}


whatsapp_service = WhatsAppService()
