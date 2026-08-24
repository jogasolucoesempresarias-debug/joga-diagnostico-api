"""
Configuração do banco PostgreSQL (SQLAlchemy 2.0 + psycopg2).
Espelha o padrão do DanfeZap: engine / SessionLocal / Base / get_db / init_db / migrate_db.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import config

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency do FastAPI: abre uma sessão e fecha ao final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 15, delay: int = 3):
    """Cria as tabelas se não existirem — com retry, pra sobreviver ao banco
    ficar pronto um pouco depois do backend subir (ordem de deploy)."""
    import logging
    import time
    logger = logging.getLogger(__name__)
    from . import models  # noqa: F401 — registra os models em Base

    for tentativa in range(1, retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("init_db: tabelas garantidas.")
            return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"init_db tentativa {tentativa}/{retries} falhou: {e}")
            time.sleep(delay)
    logger.error("init_db: não consegui criar as tabelas após %s tentativas.", retries)


def migrate_db():
    """Migrações incrementais idempotentes (rodam no lifespan, a cada start)."""
    migrations: list[str] = [
        # Diagnóstico de estoque (LP /solucoes/gestao-de-estoque): separa a origem do lead
        # no admin. 'site' = questionário geral; 'lp-estoque' = questionário da LP.
        "ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS origem VARCHAR(30) DEFAULT 'site'",
        # A LP pede menos campos que o questionário geral (nome/empresa/telefone) — cargo e
        # os demais continuam opcionais, mas 'empresa' segue obrigatória nos dois fluxos.
        "ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS analise JSONB",
    ]
    if not migrations:
        return
    with engine.connect() as conn:
        for stmt in migrations:
            conn.execute(text(stmt))
        conn.commit()
