"""
Blog da JOGA — o João escreve em /admin/blog e o site (Next, export estático) lê no build.

Fluxo: salvar/publicar aqui → (se mexeu em algo publicado) dispara `repository_dispatch` no
repo do site → a GitHub Action reconstrói o site lendo GET /api/blog/posts → deploy.

- Público:  GET /api/blog/posts (só publicados, com o HTML)  ·  GET /api/blog/img/<id>
- Admin:    /api/blog/admin (página)  ·  /api/blog/admin/api/... (header X-Admin-Token)

Segurança: o HTML vem de um editor no navegador, então é SANITIZADO no servidor (nh3) antes
de gravar — o site injeta esse HTML na página. Imagem só é aceita se for nossa (/api/blog/img/).
"""
import io
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import httpx
import nh3
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import config
from .database import get_db
from .models import Imagem, Post

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/blog", tags=["blog"])
admin_router = APIRouter(prefix="/api/blog/admin", tags=["blog-admin"])

ADMIN_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "blog_admin.html"
)

CATEGORIAS = {"estoque", "vendas", "clientes", "financeiro", "gestao"}
AUTORES = {"joao", "gabriel"}
STATUS = {"rascunho", "publicado"}

IMG_PREFIXO = "/api/blog/img/"
IMG_MAX_BYTES = 12 * 1024 * 1024   # foto de celular cabe com folga
IMG_MAX_LADO = 1600                # o artigo tem ~760 px de largura; 1600 cobre tela retina


# ─────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────

def _auth(x_admin_token: str = Header(default="")):
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Não autorizado")


# ─────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────

def slugify(texto: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    s = s[:max_len].rstrip("-")
    return s or "artigo"


def _slug_unico(db: Session, base: str, ignorar_id: int | None = None) -> str:
    slug, n = base, 2
    while True:
        q = db.query(Post).filter(Post.slug == slug)
        if ignorar_id is not None:
            q = q.filter(Post.id != ignorar_id)
        if not q.first():
            return slug
        slug, n = f"{base}-{n}", n + 1


_TAGS = {
    "p", "br", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote", "img", "hr",
}
_ATTRS = {"a": {"href"}, "img": {"src", "alt"}}


def _filtro_attr(tag: str, attr: str, valor: str):
    # Só imagem que mora no nosso banco: evita pixel de rastreio/hotlink de terceiros.
    if tag == "img" and attr == "src":
        return valor if valor.startswith(IMG_PREFIXO) else None
    return valor


def sanitizar(html: str) -> str:
    html = (html or "").replace("&nbsp;", " ").replace(" ", " ")
    limpo = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        attribute_filter=_filtro_attr,
    )
    # <img> cujo src foi barrado vira <img> vazio — tira.
    limpo = re.sub(r"<img(?![^>]*\bsrc=)[^>]*>", "", limpo)
    # Parágrafos vazios que o editor deixa no fim.
    limpo = re.sub(r"(<p>(\s|<br>)*</p>\s*)+$", "", limpo.strip())
    return limpo


def _texto_puro(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def processar_imagem(bruto: bytes) -> tuple[bytes, int, int]:
    """Abre qualquer formato que o Pillow conheça, corrige a rotação do celular, reduz
    para no máximo 1600 px e devolve WebP. Erro de formato → ValueError."""
    try:
        img = PILImage.open(io.BytesIO(bruto))
        img.load()
    except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError) as e:
        raise ValueError("Arquivo não é uma imagem válida") from e

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    img.thumbnail((IMG_MAX_LADO, IMG_MAX_LADO), PILImage.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue(), img.width, img.height


def disparar_rebuild(motivo: str) -> str:
    """Pede à GitHub Action do site que reconstrua (repository_dispatch).
    Devolve um texto curto de status para o admin mostrar. Nunca levanta exceção."""
    if not config.GITHUB_DISPATCH_TOKEN:
        logger.info("blog: rebuild NÃO disparado (GITHUB_DISPATCH_TOKEN vazio) — %s", motivo)
        return "desligado"
    url = f"https://api.github.com/repos/{config.GITHUB_DISPATCH_REPO}/dispatches"
    try:
        r = httpx.post(
            url,
            json={"event_type": "blog-atualizado", "client_payload": {"motivo": motivo[:100]}},
            headers={
                "Authorization": f"Bearer {config.GITHUB_DISPATCH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if r.status_code == 204:
            logger.info("blog: rebuild disparado — %s", motivo)
            return "disparado"
        logger.error("blog: rebuild falhou HTTP %s: %s", r.status_code, r.text[:300])
        return "falhou"
    except httpx.HTTPError as e:
        logger.error("blog: rebuild falhou: %s", e)
        return "falhou"


def _iso(d):
    return d.isoformat() if d else None


def _publico(p: Post) -> dict:
    return {
        "slug": p.slug,
        "titulo": p.titulo,
        "resumo": p.resumo or "",
        "categoria": p.categoria,
        "autor": p.autor,
        "capa": f"{IMG_PREFIXO}{p.capa_id}" if p.capa_id else None,
        "conteudo": p.conteudo or "",
        "publicado_em": _iso(p.publicado_em),
        "atualizado_em": _iso(p.atualizado_em),
    }


def _admin(p: Post, com_conteudo: bool = False) -> dict:
    d = {
        "id": p.id,
        "slug": p.slug,
        "titulo": p.titulo,
        "resumo": p.resumo or "",
        "categoria": p.categoria,
        "autor": p.autor,
        "capa_id": p.capa_id,
        "status": p.status,
        "ja_publicado": p.publicado_em is not None,
        "publicado_em": _iso(p.publicado_em),
        "criado_em": _iso(p.criado_em),
        "atualizado_em": _iso(p.atualizado_em),
    }
    if com_conteudo:
        d["conteudo"] = p.conteudo or ""
    return d


# ─────────────────────────────────────────────────────────────
# Público
# ─────────────────────────────────────────────────────────────

@public_router.get("/posts")
def posts_publicados(db: Session = Depends(get_db)):
    rows = (
        db.query(Post)
        .filter(Post.status == "publicado")
        .order_by(Post.publicado_em.desc())
        .all()
    )
    return [_publico(p) for p in rows]


@public_router.get("/img/{img_id}")
def imagem(img_id: str, db: Session = Depends(get_db)):
    if not re.fullmatch(r"[0-9a-f]{32}", img_id):
        raise HTTPException(status_code=404)
    img = db.get(Imagem, img_id)
    if not img:
        raise HTTPException(status_code=404)
    # O id nunca muda de conteúdo → cache eterno (Cloudflare + navegador).
    return Response(
        content=img.dados,
        media_type=img.mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ─────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────

class PostBody(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=200)
    resumo: str = Field("", max_length=400)
    categoria: str = "gestao"
    autor: str = "joao"
    capa_id: str | None = None
    conteudo: str = ""
    status: str = "rascunho"
    slug: str | None = Field(None, max_length=160)


def _validar(body: PostBody):
    if body.categoria not in CATEGORIAS:
        raise HTTPException(422, "Categoria inválida")
    if body.autor not in AUTORES:
        raise HTTPException(422, "Autor inválido")
    if body.status not in STATUS:
        raise HTTPException(422, "Status inválido")
    if body.capa_id and not re.fullmatch(r"[0-9a-f]{32}", body.capa_id):
        raise HTTPException(422, "Capa inválida")


def _checar_publicavel(p: Post):
    faltando = []
    if not (p.resumo or "").strip():
        faltando.append("resumo")
    if len(_texto_puro(p.conteudo)) < 200:
        faltando.append("texto (mínimo de 200 caracteres)")
    if faltando:
        raise HTTPException(422, "Para publicar falta: " + ", ".join(faltando))


@admin_router.get("")
async def pagina():
    return FileResponse(ADMIN_HTML, media_type="text/html")


@admin_router.get("/api/status", dependencies=[Depends(_auth)])
def status():
    return {"rebuild_configurado": bool(config.GITHUB_DISPATCH_TOKEN)}


@admin_router.get("/api/posts", dependencies=[Depends(_auth)])
def listar(db: Session = Depends(get_db)):
    rows = db.query(Post).order_by(Post.atualizado_em.desc()).all()
    return [_admin(p) for p in rows]


@admin_router.get("/api/posts/{post_id}", dependencies=[Depends(_auth)])
def detalhe(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Artigo não encontrado")
    return _admin(p, com_conteudo=True)


def _aplicar(db: Session, p: Post, body: PostBody):
    p.titulo = body.titulo.strip()
    p.resumo = body.resumo.strip()
    p.categoria = body.categoria
    p.autor = body.autor
    p.capa_id = body.capa_id or None
    p.conteudo = sanitizar(body.conteudo)
    # Endereço só muda enquanto o artigo nunca foi ao ar — depois disso, link compartilhado
    # e Google já apontam para ele.
    if p.publicado_em is None:
        base = slugify(body.slug or body.titulo)
        p.slug = _slug_unico(db, base, ignorar_id=p.id)


def _salvar_e_rebuild(db: Session, p: Post, status_novo: str, estava_no_ar: bool) -> dict:
    if status_novo == "publicado":
        _checar_publicavel(p)
        if p.publicado_em is None:
            p.publicado_em = datetime.now(timezone.utc)
    p.status = status_novo
    p.atualizado_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)

    site = "sem_mudanca"
    if estava_no_ar or status_novo == "publicado":
        site = disparar_rebuild(f"{status_novo}: {p.slug}")
    return {"post": _admin(p, com_conteudo=True), "site": site}


@admin_router.post("/api/posts", dependencies=[Depends(_auth)])
def criar(body: PostBody, db: Session = Depends(get_db)):
    _validar(body)
    p = Post(slug="tmp-" + uuid.uuid4().hex[:12], titulo=body.titulo)
    _aplicar(db, p, body)
    db.add(p)
    db.flush()
    return _salvar_e_rebuild(db, p, body.status, estava_no_ar=False)


@admin_router.put("/api/posts/{post_id}", dependencies=[Depends(_auth)])
def atualizar(post_id: int, body: PostBody, db: Session = Depends(get_db)):
    _validar(body)
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Artigo não encontrado")
    estava_no_ar = p.status == "publicado"
    _aplicar(db, p, body)
    return _salvar_e_rebuild(db, p, body.status, estava_no_ar=estava_no_ar)


@admin_router.delete("/api/posts/{post_id}", dependencies=[Depends(_auth)])
def apagar(post_id: int, db: Session = Depends(get_db)):
    p = db.get(Post, post_id)
    if not p:
        raise HTTPException(404, "Artigo não encontrado")
    estava_no_ar = p.status == "publicado"
    slug = p.slug
    db.delete(p)
    db.commit()
    site = disparar_rebuild(f"apagado: {slug}") if estava_no_ar else "sem_mudanca"
    return {"ok": True, "site": site}


@admin_router.post("/api/imagens", dependencies=[Depends(_auth)])
async def enviar_imagem(arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    bruto = await arquivo.read(IMG_MAX_BYTES + 1)
    if len(bruto) > IMG_MAX_BYTES:
        raise HTTPException(413, "Imagem maior que 12 MB")
    try:
        dados, w, h = processar_imagem(bruto)
    except ValueError as e:
        raise HTTPException(422, str(e))
    img = Imagem(id=uuid.uuid4().hex, mime="image/webp", dados=dados, largura=w, altura=h)
    db.add(img)
    db.commit()
    return {"id": img.id, "url": f"{IMG_PREFIXO}{img.id}", "largura": w, "altura": h}
