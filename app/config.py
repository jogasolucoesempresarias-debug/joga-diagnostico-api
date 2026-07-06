"""
Configuração via variáveis de ambiente (dotenv + os.getenv).
Espelha o padrão do DanfeZap: classe Config exposta como singleton `config`.
"""
from dotenv import load_dotenv
import os

load_dotenv()


def _lista(valor: str) -> list:
    """Converte 'a@x.com, b@y.com' -> ['a@x.com', 'b@y.com'] (sem vazios)."""
    return [item.strip() for item in (valor or "").split(",") if item.strip()]


class Config:
    # IA
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    # Banco
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/joga_diagnostico",
    )

    # WhatsApp (UazAPI)
    UAZAPI_URL = os.getenv("UAZAPI_URL", "https://free.uazapi.com")
    UAZAPI_TOKEN = os.getenv("UAZAPI_TOKEN", "")

    # E-mail (Resend)
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    RESEND_FROM = os.getenv("RESEND_FROM", "joga@jogasolucoes.com.br")

    # Pré-brief (João + equipe)
    JOAO_WHATSAPP = os.getenv("JOAO_WHATSAPP", "5528999920221")
    PREBRIEF_EMAILS = _lista(
        os.getenv(
            "PREBRIEF_EMAILS",
            "joga@jogasolucoes.com.br,jjvictorep@gmail.com,ggabriel.milho@gmail.com",
        )
    )

    # CORS
    ALLOWED_ORIGINS = _lista(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))

    # Token da página de admin (/api/diagnostico/admin). Trocar em produção.
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "joga-admin")

    # Flag mestra: false = não dispara WhatsApp/e-mail real, só loga (modo dev)
    ENVIO_ATIVO = os.getenv("ENVIO_ATIVO", "false").lower() == "true"

    # Flag do aviso pro cliente (e-mail de "recebido"). Fica OFF até a JOGA ter a
    # própria instância UazAPI/infra — por ora a JOGA é quem contata o cliente.
    AVISO_CLIENTE_ATIVO = os.getenv("AVISO_CLIENTE_ATIVO", "false").lower() == "true"

    TZ = os.getenv("TZ", "America/Sao_Paulo")


config = Config()
