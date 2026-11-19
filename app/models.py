"""
Model da tabela `diagnosticos` — um registro por lead que conclui o questionário.

LGPD: na Fase 2a guardamos apenas os dados do lead + respostas + placar + relatório.
Nenhum arquivo bruto é persistido (upload de planilha é Fase 2b; `achados` fica reservado).
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .database import Base


class Diagnostico(Base):
    __tablename__ = "diagnosticos"

    id = Column(Integer, primary_key=True, index=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    # Contato / contexto
    nome = Column(String(120), nullable=False)
    empresa = Column(String(160), nullable=False)
    cargo = Column(String(120))
    whatsapp = Column(String(30))
    email = Column(String(160))
    setor = Column(String(40))
    erp = Column(String(60))
    desafio = Column(Text)
    urgencia = Column(String(40))
    faturamento = Column(String(40))
    colaboradores = Column(String(40))

    # Respostas e resultado
    respostas = Column(JSONB)
    placar = Column(JSONB)
    relatorio = Column(Text)

    # Reservado p/ Fase 2b (upload de planilha)
    tem_planilha = Column(Boolean, default=False)
    achados = Column(JSONB, nullable=True)

    # Controle de envio
    prebrief_enviado = Column(Boolean, default=False)

    # Origem do lead: 'site' (questionário geral) ou 'lp-estoque' (LP de Gestão de Estoque).
    origem = Column(String(30), default="site")
    # Análise estruturada mostrada ao cliente na tela (só no fluxo da LP): leitura/pontos/fecho.
    analise = Column(JSONB, nullable=True)


def salvar(
    db,
    *,
    contato: dict,
    respostas: dict,
    placar: dict,
    relatorio: str,
    origem: str = "site",
    analise: dict | None = None,
) -> "Diagnostico":
    """Persiste um novo diagnóstico e devolve o objeto salvo (com id).

    `origem`/`analise` são usados pelo fluxo da LP de estoque; o questionário geral chama
    sem eles e continua gravando exatamente como antes.
    """
    registro = Diagnostico(
        origem=origem,
        analise=analise,
        nome=contato.get("nome"),
        empresa=contato.get("empresa"),
        cargo=contato.get("cargo"),
        whatsapp=contato.get("whatsapp"),
        email=contato.get("email"),
        setor=contato.get("setor"),
        erp=contato.get("erp"),
        desafio=contato.get("desafio"),
        urgencia=contato.get("urgencia"),
        faturamento=contato.get("faturamento"),
        colaboradores=contato.get("colaboradores"),
        respostas=respostas,
        placar=placar,
        relatorio=relatorio,
        tem_planilha=False,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def atualizar_achados(db, diagnostico_id: int, achados: dict) -> bool:
    """Salva os achados da planilha (Fase 2b) no registro. LGPD: só os achados, nunca o arquivo."""
    registro = db.query(Diagnostico).filter(Diagnostico.id == diagnostico_id).first()
    if not registro:
        return False
    registro.achados = achados
    registro.tem_planilha = True
    db.commit()
    return True


# ─────────────────────────────────────────────────────────────
# Blog (jogasolucoes.com.br/blog) — o João escreve em /admin/blog, o site lê no build.
# Imagens ficam NO POSTGRES (bytea): o backup diário só pega pg_dump, então arquivo em
# volume ficaria de fora. São poucas e já chegam reduzidas (≤ 1600 px, WebP).
# ─────────────────────────────────────────────────────────────
from sqlalchemy import LargeBinary  # noqa: E402


class Post(Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(160), unique=True, nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    resumo = Column(String(400), default="")
    categoria = Column(String(30), default="gestao")
    autor = Column(String(30), default="joao")
    capa_id = Column(String(32), nullable=True)
    conteudo = Column(Text, default="")  # HTML já sanitizado (nh3) no salvamento
    # 'rascunho' | 'publicado'
    status = Column(String(20), default="rascunho", nullable=False)
    publicado_em = Column(DateTime(timezone=True), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Imagem(Base):
    __tablename__ = "blog_imagens"

    id = Column(String(32), primary_key=True)  # uuid4 hex — vira a URL /api/blog/img/<id>
    mime = Column(String(40), nullable=False)
    dados = Column(LargeBinary, nullable=False)
    largura = Column(Integer)
    altura = Column(Integer)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
