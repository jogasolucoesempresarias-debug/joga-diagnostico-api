"""
Blog: sanitização, slug, imagem e o fluxo rascunho → publicado → fora do ar.
Banco: SQLite em memória só com as 2 tabelas do blog (Diagnostico usa JSONB, que o SQLite
não tem). Rebuild do site é monkeypatchado — nenhum teste chama o GitHub.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import blog, main
from app.config import config
from app.database import get_db
from app.models import Imagem, Post

TOKEN = "tok-teste"
H = {"X-Admin-Token": TOKEN}
TEXTO = "<p>" + ("Estoque parado é dinheiro parado. " * 10) + "</p>"


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Post.__table__.create(engine)
    Imagem.__table__.create(engine)
    Sess = sessionmaker(bind=engine)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    disparos = []
    monkeypatch.setattr(config, "ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(blog, "disparar_rebuild", lambda motivo: disparos.append(motivo) or "disparado")
    main.app.dependency_overrides[get_db] = _db
    c = TestClient(main.app)
    c.disparos = disparos
    yield c
    main.app.dependency_overrides.clear()


def _png(w=3000, h=2000) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), (244, 165, 42)).save(buf, format="PNG")
    return buf.getvalue()


# ── unidades ─────────────────────────────────────────────────

def test_slugify_tira_acento_e_simbolo():
    assert blog.slugify("Curva ABC: o que é e por quê?") == "curva-abc-o-que-e-e-por-que"
    assert blog.slugify("!!!") == "artigo"


def test_sanitizar_remove_script_evento_e_imagem_externa():
    sujo = (
        '<p onclick="x()">Oi<script>alert(1)</script></p>'
        '<img src="https://rastreio.com/pixel.gif">'
        '<img src="/api/blog/img/' + "a" * 32 + '" alt="ok">'
        '<a href="javascript:alert(1)">mau</a> <a href="https://joga.com">bom</a>'
        "<p>a&nbsp;b</p><p><br></p>"
    )
    limpo = blog.sanitizar(sujo)
    assert "script" not in limpo and "onclick" not in limpo
    assert "rastreio.com" not in limpo
    assert 'src="/api/blog/img/' + "a" * 32 in limpo
    assert "javascript" not in limpo
    assert 'rel="noopener noreferrer"' in limpo
    assert "a b" in limpo
    assert not limpo.endswith("<p><br></p>")


def test_processar_imagem_reduz_e_vira_webp():
    dados, w, h = blog.processar_imagem(_png())
    assert (w, h) == (1600, 1067)
    assert dados[:4] == b"RIFF" and dados[8:12] == b"WEBP"


def test_processar_imagem_recusa_arquivo_que_nao_e_imagem():
    with pytest.raises(ValueError):
        blog.processar_imagem(b"isto nao e imagem")


# ── API ──────────────────────────────────────────────────────

def test_admin_exige_token(client):
    assert client.get("/api/blog/admin/api/posts").status_code == 401
    assert client.get("/api/blog/admin/api/posts", headers={"X-Admin-Token": "errado"}).status_code == 401


def test_rascunho_nao_aparece_e_nao_dispara(client):
    r = client.post("/api/blog/admin/api/posts", headers=H, json={"titulo": "Curva ABC na prática", "conteudo": TEXTO})
    assert r.status_code == 200, r.text
    assert r.json()["post"]["slug"] == "curva-abc-na-pratica"
    assert r.json()["site"] == "sem_mudanca"
    assert client.get("/api/blog/posts").json() == []
    assert client.disparos == []


def test_publicar_exige_resumo_e_texto(client):
    r = client.post("/api/blog/admin/api/posts", headers=H, json={"titulo": "Curto", "status": "publicado", "conteudo": "<p>oi</p>"})
    assert r.status_code == 422
    assert "resumo" in r.json()["detail"] and "texto" in r.json()["detail"]


def test_fluxo_publicar_editar_despublicar(client):
    novo = client.post("/api/blog/admin/api/posts", headers=H, json={
        "titulo": "Ruptura no atacado", "resumo": "Como medir.", "categoria": "estoque",
        "conteudo": TEXTO, "status": "rascunho",
    }).json()["post"]
    pid = novo["id"]

    corpo = {"titulo": "Ruptura no atacado", "resumo": "Como medir.", "categoria": "estoque", "conteudo": TEXTO, "status": "publicado"}
    r = client.put(f"/api/blog/admin/api/posts/{pid}", headers=H, json=corpo).json()
    assert r["site"] == "disparado" and r["post"]["ja_publicado"]
    pub = client.get("/api/blog/posts").json()
    assert [p["slug"] for p in pub] == ["ruptura-no-atacado"]
    assert "Estoque parado" in pub[0]["conteudo"]

    # Depois de publicado, trocar o título NÃO muda o endereço.
    corpo["titulo"] = "Ruptura no atacado: guia completo"
    r = client.put(f"/api/blog/admin/api/posts/{pid}", headers=H, json=corpo).json()
    assert r["post"]["slug"] == "ruptura-no-atacado"
    assert len(client.disparos) == 2

    # Tirar do ar também reconstrói o site.
    corpo["status"] = "rascunho"
    r = client.put(f"/api/blog/admin/api/posts/{pid}", headers=H, json=corpo).json()
    assert r["site"] == "disparado"
    assert client.get("/api/blog/posts").json() == []


def test_slug_repetido_ganha_sufixo(client):
    a = client.post("/api/blog/admin/api/posts", headers=H, json={"titulo": "Giro de estoque"}).json()["post"]
    b = client.post("/api/blog/admin/api/posts", headers=H, json={"titulo": "Giro de estoque"}).json()["post"]
    assert (a["slug"], b["slug"]) == ("giro-de-estoque", "giro-de-estoque-2")


def test_upload_e_leitura_de_imagem(client):
    r = client.post("/api/blog/admin/api/imagens", headers=H, files={"arquivo": ("foto.png", _png(800, 600), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    img = client.get(url)
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/webp"
    assert "immutable" in img.headers["cache-control"]
    assert client.get("/api/blog/img/" + "0" * 32).status_code == 404
    assert client.get("/api/blog/img/../../etc").status_code == 404


def test_upload_recusa_nao_imagem(client):
    r = client.post("/api/blog/admin/api/imagens", headers=H, files={"arquivo": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 422


def test_apagar_publicado_dispara(client):
    pid = client.post("/api/blog/admin/api/posts", headers=H, json={
        "titulo": "Mix de produtos", "resumo": "r", "conteudo": TEXTO, "status": "publicado",
    }).json()["post"]["id"]
    client.disparos.clear()
    assert client.delete(f"/api/blog/admin/api/posts/{pid}", headers=H).json()["site"] == "disparado"
    assert client.get("/api/blog/posts").json() == []


def test_atalho_admin_blog(client):
    r = client.get("/admin/blog", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/api/blog/admin"
    assert "Blog JOGA" in client.get("/api/blog/admin").text
