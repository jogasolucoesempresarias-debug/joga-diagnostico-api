"""
Testes do diagnóstico de ESTOQUE (LP /solucoes/gestao-de-estoque).

Cobre o que dói se quebrar: o placar (puro), a trava contra cifra inventada pela IA,
e o contrato do endpoint — incluindo o que NÃO deve acontecer (envio ao cliente).
"""
import pytest

from app import estoque_scoring as sc
from app import estoque_ia


# ───────────────────────── Scoring ─────────────────────────

def _todas(valor: str) -> dict:
    return {q: valor for q in sc.PERGUNTAS}


def test_tudo_sim_e_maduro_em_todas_as_areas():
    r = sc.calcular(_todas("sim"))
    assert set(r["placar"]) == set(sc.AREAS)
    assert all(nivel == "Maduro" for nivel in r["placar"].values())
    assert r["resumo"]["sim"] == 12


def test_tudo_nao_e_critico_em_todas_as_areas():
    r = sc.calcular(_todas("nao"))
    assert all(nivel == "Crítico" for nivel in r["placar"].values())
    # Toda área fraca vira oportunidade — não trava num número fixo.
    assert len(r["oportunidades"]) == len(sc.AREAS)


def test_mais_ou_menos_cai_entre_sim_e_nao():
    meio = sc.calcular(_todas("mais_ou_menos"))["fracoes"][sc.AREA_COMPRAS]
    assert 0 < meio < 1
    assert meio == pytest.approx(0.5)


def test_resposta_ausente_ou_desconhecida_nao_quebra():
    r = sc.calcular({"e1": "sim", "e2": "chute_invalido"})
    assert r["placar"][sc.AREA_PARADO] == "Atenção"   # 2 de 4 pontos
    assert r["resumo"]["respondidas"] == 1


def test_placar_vazio_nao_quebra():
    r = sc.calcular({})
    assert all(n == "Crítico" for n in r["placar"].values())
    assert r["maior_dor"]["area"] in sc.AREAS


def test_maior_dor_desempata_pela_prioridade():
    # Todas iguais em zero → vence a primeira da PRIORIDADE (capital parado).
    r = sc.calcular(_todas("nao"))
    assert r["maior_dor"]["area"] == sc.AREA_PARADO
    assert r["maior_dor"]["ancora"]


def test_area_mais_fraca_vem_primeiro_nas_oportunidades():
    respostas = _todas("sim")
    for q, area in sc.PERGUNTAS.items():
        if area == sc.AREA_VALIDADE:
            respostas[q] = "nao"
    r = sc.calcular(respostas)
    assert r["oportunidades"][0]["area"] == sc.AREA_VALIDADE
    assert r["maior_dor"]["area"] == sc.AREA_VALIDADE


def test_placar_maduro_nao_gera_oportunidade_fabricada():
    """Regressão: havia um `or ordenadas[:1]` que entregava uma 'área fraca' mesmo com tudo
    Maduro — e a IA obedientemente inventava um defeito ('você controla, MAS mesmo assim...').
    Numa página cuja tese é 'não é promessa, é prova', dor fabricada é o pior erro."""
    r = sc.calcular(_todas("sim"))
    assert r["maduro"] is True
    assert r["oportunidades"] == []


def test_acompanhamento_e_a_ancora_quando_e_o_unico_problema():
    """Regressão: a preferência por áreas substantivas mandava a equipe para a call falando
    de 'capital parado' numa operação Madura nisso, quando o único buraco era o alerta."""
    respostas = _todas("sim")
    respostas["e11"] = respostas["e12"] = "nao"
    r = sc.calcular(respostas)
    assert r["maduro"] is False
    assert r["maior_dor"]["area"] == sc.AREA_ACOMPANHAMENTO


def test_substantiva_ganha_a_ancora_quando_as_duas_estao_fracas():
    respostas = _todas("nao")
    r = sc.calcular(respostas)
    assert r["maior_dor"]["area"] == sc.AREA_PARADO
    # ...mas Acompanhamento continua na lista, por último (fecha melhor a narrativa).
    assert r["oportunidades"][-1]["area"] == sc.AREA_ACOMPANHAMENTO


def test_stub_maduro_nao_inventa_defeito():
    r = sc.calcular(_todas("sim"))
    analise = estoque_ia._stub(r)
    assert "Próximo passo" in analise["pontos"][0]["titulo"]
    assert "mas" not in analise["leitura"].lower().split()


def test_desafio_sintetico_nunca_vazio():
    assert sc.desafio_sintetico(sc.calcular(_todas("nao")))
    assert sc.desafio_sintetico(sc.calcular(_todas("sim")))


# ───────────────────────── Trava anti-cifra ─────────────────────────
# A IA recebe 12 respostas em escala e nada mais: qualquer valor em dinheiro é invenção.

@pytest.mark.parametrize(
    "texto",
    [
        "Você tem cerca de R$ 200 mil parados.",
        "São aproximadamente 200 mil reais em risco.",
        "Isso representa um milhão em capital empatado.",
    ],
)
def test_cifra_em_ponto_e_removida(texto):
    analise = {
        "leitura": "Sua operação não acompanha cobertura.",
        "pontos": [
            {"titulo": "Capital parado", "texto": texto},
            {"titulo": "Ruptura", "texto": "Você não acompanha ruptura por comprador."},
        ],
        "fecho": "Comece pelo capital parado.",
    }
    limpa = estoque_ia._sem_cifras(analise)
    assert len(limpa["pontos"]) == 1
    assert limpa["pontos"][0]["titulo"] == "Ruptura"


def test_cifra_na_leitura_descarta_a_analise_inteira():
    analise = {
        "leitura": "Sua empresa pode ter R$ 300 mil parados.",
        "pontos": [{"titulo": "X", "texto": "sem cifra aqui"}],
        "fecho": "ok",
    }
    assert estoque_ia._sem_cifras(analise) == {}


def test_analise_sem_cifra_passa_intacta():
    analise = {
        "leitura": "Você não acompanha cobertura em dias.",
        "pontos": [{"titulo": "Compras no feeling", "texto": "Sem cobertura-alvo definida."}],
        "fecho": "Comece por compras.",
    }
    assert estoque_ia._sem_cifras(dict(analise)) == analise


def test_stub_funciona_sem_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = sc.calcular(_todas("nao"))
    analise = estoque_ia.gerar({"empresa": "X"}, _todas("nao"), {}, r)
    assert analise["leitura"] and analise["pontos"] and analise["fecho"]


# ───────────────────────── Endpoint ─────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # usa o stub, sem chamar a OpenAI
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


CORPO = {
    "nome": "Gabriel",
    "empresa": "Distribuidora Teste",
    "whatsapp": "34999434613",
    "consent": True,
    "setor": "atacado",
    "erp": "winthor",
    "skus": "2000_5000",
    "respostas": {q: "nao" for q in sc.PERGUNTAS},
}


def test_endpoint_devolve_placar_e_analise(client, monkeypatch):
    salvos = {}
    monkeypatch.setattr(
        "app.models.salvar",
        lambda db, **kw: salvos.update(kw) or type("R", (), {"id": 1})(),
    )
    r = client.post("/api/diagnostico/estoque", json=CORPO)
    assert r.status_code == 200
    body = r.json()
    assert set(body["placar"]) == set(sc.AREAS)
    assert body["analise"]["leitura"]
    assert body["resumo"]["nao"] == 12
    # Marcado como lead da LP, para separar no admin.
    assert salvos["origem"] == "lp-estoque"


def test_endpoint_exige_consentimento(client):
    r = client.post("/api/diagnostico/estoque", json={**CORPO, "consent": False})
    assert r.status_code == 422


def test_endpoint_exige_whatsapp(client):
    corpo = {k: v for k, v in CORPO.items() if k != "whatsapp"}
    r = client.post("/api/diagnostico/estoque", json=corpo)
    assert r.status_code == 422


def test_nao_dispara_nada_para_o_cliente(client, monkeypatch):
    """O cliente lê a análise na tela; e-mail e WhatsApp são só para a equipe JOGA."""
    chamados = []
    monkeypatch.setattr("app.models.salvar", lambda db, **kw: type("R", (), {"id": 1})())
    monkeypatch.setattr("app.prebrief.enviar_equipe", lambda *a, **k: chamados.append("equipe"))
    monkeypatch.setattr(
        "app.prebrief.enviar_aviso_cliente", lambda *a, **k: chamados.append("cliente")
    )
    client.post("/api/diagnostico/estoque", json=CORPO)
    assert "equipe" in chamados
    assert "cliente" not in chamados
