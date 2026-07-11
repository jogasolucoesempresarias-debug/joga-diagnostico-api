"""Testes do scoring de maturidade (puro, sem IA nem banco)."""
from app import scoring

PIOR = {
    "q5": "cabeca", "q6": "problema", "q7": "mais",
    "q8": "faturamento", "q9": "sem_metas", "q10": "nao",
    "q19": "lucro_faturamento", "q20": "inad_nao", "q21": "dre_nunca",
    "q11": "nao_ideia", "q12": "nao", "q13": "nao_sei",
    "q14": "nao", "q15": "sempre", "q16": "feeling",
}

MELHOR = {
    "q5": "bi", "q6": "dia", "q7": "quase_nada",
    "q8": "margem_completa", "q9": "de_perto", "q10": "facil",
    "q19": "lucro_exato", "q20": "inad_controlo", "q21": "dre_mes",
    "q11": "exato", "q12": "formal", "q13": "menos10",
    "q14": "exato", "q15": "raramente", "q16": "dados",
}


def test_tudo_pior_da_critico_em_todas_areas():
    r = scoring.calcular(PIOR, setor="atacado")
    assert r["placar"] == {
        "Dados": "Crítico", "Comercial": "Crítico", "Financeiro": "Crítico",
        "Gestão de Clientes": "Crítico", "Estoque": "Crítico",
    }
    # todas as 5 áreas críticas viram oportunidade (não trava em 3)
    assert len(r["oportunidades"]) == 5


def test_tudo_melhor_da_maduro():
    r = scoring.calcular(MELHOR, setor="atacado")
    assert all(nivel == "Maduro" for nivel in r["placar"].values())


def test_servicos_nao_pontua_estoque():
    r = scoring.calcular(PIOR, setor="servicos")
    assert "Estoque" not in r["placar"]
    assert set(r["placar"].keys()) == {"Dados", "Comercial", "Financeiro", "Gestão de Clientes"}
    assert len(r["oportunidades"]) == 4  # serviços: 4 áreas, todas críticas


def test_inadimplencia_nao_vende_a_prazo_nao_penaliza():
    # 'não vendo a prazo' = nota cheia em q20 (sem risco de inadimplência)
    fin = {"q19": "lucro_exato", "q20": "inad_nao_prazo", "q21": "dre_mes"}
    r = scoring.calcular(fin, setor="varejo")
    assert r["placar"]["Financeiro"] == "Maduro"


def test_respostas_ausentes_valem_zero():
    # Sem nenhuma resposta -> tudo Crítico (fração 0)
    r = scoring.calcular({}, setor="varejo")
    assert all(nivel == "Crítico" for nivel in r["placar"].values())


def test_maior_dor_traz_ancora():
    r = scoring.calcular(PIOR, setor="atacado")
    dor = r["maior_dor"]
    assert dor["area"] in r["placar"]
    assert dor["ancora"]  # string não vazia


def test_dados_nivel_intermediario():
    # q5=erp(2), q6=semana(2), q7=horas(2) -> 6/9 = 0.67 -> Bom
    respostas = {"q5": "erp", "q6": "semana", "q7": "horas"}
    r = scoring.calcular(respostas, setor="industria")
    assert r["placar"]["Dados"] == "Bom"
