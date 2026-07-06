"""
Teste do endpoint /api/diagnostico/submit com banco e IA mockados.
Não exige Postgres nem chave OpenAI (ENVIO_ATIVO fica false -> sem rede).
"""
from fastapi.testclient import TestClient

from app import main, models
from app.database import get_db


class _FakeRegistro:
    id = 123


def _fake_db():
    yield None


def _setup(monkeypatch):
    # Sem banco: get_db devolve None e salvar() não toca no Postgres.
    main.app.dependency_overrides[get_db] = _fake_db
    monkeypatch.setattr(models, "salvar", lambda *a, **k: _FakeRegistro())


def test_submit_retorna_placar_e_oportunidades(monkeypatch):
    _setup(monkeypatch)
    client = TestClient(main.app)

    payload = {
        "nome": "Fulano Teste",
        "empresa": "Atacado Exemplo",
        "email": "fulano@exemplo.com",
        "consent": True,
        "setor": "atacado",
        "respostas": {
            "q5": "cabeca", "q6": "problema", "q7": "mais",
            "q8": "faturamento", "q9": "sem_metas", "q10": "nao",
            "q11": "nao_ideia", "q12": "nao", "q13": "nao_sei",
            "q14": "nao", "q15": "sempre", "q16": "feeling",
        },
    }
    resp = client.post("/api/diagnostico/submit", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 123
    assert data["placar"]["Carteira"] == "Crítico"
    assert len(data["oportunidades"]) == 3
    assert "48h" in data["mensagem"]

    main.app.dependency_overrides.clear()


def test_submit_exige_consent(monkeypatch):
    _setup(monkeypatch)
    client = TestClient(main.app)
    payload = {
        "nome": "Sem Consent",
        "empresa": "X",
        "email": "x@x.com",
        "consent": False,
        "respostas": {},
    }
    resp = client.post("/api/diagnostico/submit", json=payload)
    assert resp.status_code == 422  # validação Pydantic
    main.app.dependency_overrides.clear()


def test_submit_exige_contato(monkeypatch):
    _setup(monkeypatch)
    client = TestClient(main.app)
    payload = {"nome": "Sem Contato", "empresa": "X", "consent": True, "respostas": {}}
    resp = client.post("/api/diagnostico/submit", json=payload)
    assert resp.status_code == 422
    main.app.dependency_overrides.clear()


def test_health():
    client = TestClient(main.app)
    resp = client.get("/api/diagnostico/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
