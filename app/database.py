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


def init_db():
    """Cria as tabelas registradas em Base.metadata se ainda não existirem."""
    from . import models  # noqa: F401 — registra os models em Base
    Base.metadata.create_all(bind=engine)


def migrate_db():
    """Migrações incrementais idempotentes (vazio por ora — reservado p/ Fase 2b)."""
    migrations: list[str] = [
        # Ex. futuro (Fase 2b): "ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS achados JSONB",
    ]
    if not migrations:
        return
    with engine.connect() as conn:
        for stmt in migrations:
            conn.execute(text(stmt))
        conn.commit()
