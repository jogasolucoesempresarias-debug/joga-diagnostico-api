"""
Testes do motor de planilha (Fase 2b) — foco no analise.py:
dois formatos (transacional / agregado), caso SEM lucro e detecção de colunas.
Nenhuma rede (parsers_erp é determinístico; não usa a IA).
"""
from datetime import date, timedelta

import pandas as pd

from app.planilha import analise, parsers_erp


def _iso(d: date) -> str:
    return d.strftime("%d/%m/%Y")  # formato BR de propósito (testa a conversão)


def test_transacional_sem_lucro_calcula_inativos():
    hoje = date(2026, 6, 30)
    linhas = []
    # 10 clientes ativos (compraram há poucos dias), 5 inativos (há 120 dias)
    for i in range(10):
        linhas.append({"Cliente": f"Ativo {i}", "Data": _iso(hoje - timedelta(days=5)), "Total": "1.000,00"})
        linhas.append({"Cliente": f"Ativo {i}", "Data": _iso(hoje - timedelta(days=35)), "Total": "800,00"})
    for i in range(5):
        linhas.append({"Cliente": f"Inativo {i}", "Data": _iso(hoje - timedelta(days=120)), "Total": "500,00"})
    df = pd.DataFrame(linhas)

    mapa = parsers_erp.detectar(df.columns)
    assert mapa["cliente"] == "Cliente" and mapa["valor"] == "Total" and mapa["data_compra"] == "Data"

    achados = analise.analisar(df, mapa)
    assert achados["ok"] is True
    assert achados["formato"] == "transacional"
    assert achados["total_clientes"] == 15
    # 5 de 15 inativos há 120 dias (>60)
    assert achados["n_inativos_60d"] == 5
    assert round(achados["pct_inativos_60d"], 2) == round(5 / 15, 2)
    # achados nunca citam R$
    assert not any("R$" in f for f in achados["frases"])


def test_agregado_uma_linha_por_cliente():
    hoje = date(2026, 6, 30)
    # Recência é relativa à data mais recente do arquivo (A = âncora, dias=0).
    linhas = [
        {"cliente": "A", "ultima_compra": _iso(hoje), "faturamento": "5000"},
        {"cliente": "B", "ultima_compra": _iso(hoje - timedelta(days=200)), "faturamento": "1200"},
        {"cliente": "C", "ultima_compra": _iso(hoje - timedelta(days=90)), "faturamento": "300"},
    ]
    df = pd.DataFrame(linhas)
    mapa = parsers_erp.detectar(df.columns)
    assert mapa["cliente"] == "cliente" and mapa["valor"] == "faturamento"

    achados = analise.analisar(df, mapa)
    assert achados["formato"] == "agregado"
    assert achados["total_clientes"] == 3
    # B (200d) e C (90d) estão >60d da âncora
    assert achados["n_inativos_60d"] == 2


def test_valor_br_e_datas_br_sao_convertidos():
    df = pd.DataFrame([
        {"cliente": "X", "data": "15/01/2026", "valor": "1.234,56"},
        {"cliente": "X", "data": "20/02/2026", "valor": "2.000,00"},
    ])
    mapa = parsers_erp.detectar(df.columns)
    achados = analise.analisar(df, mapa)
    assert achados["ok"] is True
    assert achados["total_clientes"] == 1


def test_planilha_sem_colunas_uteis():
    df = pd.DataFrame([{"foo": "1", "bar": "2"}])
    mapa = parsers_erp.detectar(df.columns)
    assert not parsers_erp.confiante(mapa)  # camada 1 não confia → iria pra IA/modelo


def test_pareto_concentracao():
    hoje = date(2026, 6, 30)
    # 1 cliente gigante + 9 pequenos
    linhas = [{"cliente": "Gigante", "data": _iso(hoje), "valor": "100000"}]
    for i in range(9):
        linhas.append({"cliente": f"P{i}", "data": _iso(hoje), "valor": "1000"})
    df = pd.DataFrame(linhas)
    achados = analise.analisar(df, parsers_erp.detectar(df.columns))
    assert "pct_faturamento_top20" in achados
    assert achados["pct_faturamento_top20"] > 0.8  # gigante domina
