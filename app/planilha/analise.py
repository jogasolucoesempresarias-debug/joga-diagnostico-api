"""
Análise da carteira a partir da planilha mapeada (Fase 2b).

Ponte entre o DataFrame (colunas já mapeadas para {cliente, data_compra, valor})
e as funções puras de `rfm.py`. Piso = 3 colunas; **custo/lucro são opcionais**
(o diagnóstico grátis usa faturamento como monetário). Nenhum valor em R$ nos achados.

Trata os DOIS formatos aceitos:
- **transacional**: várias linhas por cliente → recência + frequência + ciclo + segmentação.
- **agregado**: 1 linha por cliente (última compra + total) → análise leve (recência + valor).
"""
import math
import re
from datetime import date, timedelta

import pandas as pd

from . import rfm

INATIVO_DIAS = 60  # "sem comprar há 60+ dias" (spec §4 q11/q13)


def _to_float(x) -> float | None:
    """Converte número em formatos variados (inclui BR '1.234,56') para float."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if (isinstance(x, float) and math.isnan(x)) else float(x)
    s = str(x).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)  # tira R$, espaços, etc.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")   # BR: ponto milhar, vírgula decimal
    elif "," in s:
        s = s.replace(",", ".")                     # só vírgula = decimal
    try:
        return float(s)
    except ValueError:
        return None


def _preparar(df: pd.DataFrame, mapeamento: dict) -> pd.DataFrame:
    """Extrai e limpa as 3 colunas do piso a partir do mapeamento."""
    col_cli = mapeamento.get("cliente")
    col_val = mapeamento.get("valor")
    col_data = mapeamento.get("data_compra")

    out = pd.DataFrame()
    out["cli"] = df[col_cli].astype(str).str.strip() if col_cli in df.columns else None
    out["val"] = df[col_val].map(_to_float) if col_val in df.columns else None
    if col_data and col_data in df.columns:
        out["data"] = pd.to_datetime(df[col_data], dayfirst=True, errors="coerce").dt.date
    else:
        out["data"] = pd.NaT

    out = out[out["cli"].notna() & (out["cli"] != "") & (out["cli"].str.lower() != "nan")]
    out = out[out["val"].notna()]
    return out.reset_index(drop=True)


def _detectar_formato(df: pd.DataFrame) -> str:
    tem_data = df["data"].notna().any()
    if not tem_data:
        return "sem_data"
    n_cli = df["cli"].nunique()
    if n_cli == 0:
        return "sem_data"
    linhas_por_cli = len(df) / n_cli
    return "transacional" if linhas_por_cli >= 1.3 else "agregado"


def _build_snapshot(df: pd.DataFrame, formato: str, anchor: date):
    snapshot, datas_por_cliente, meta = [], {}, {}
    cutoff12m = anchor - timedelta(days=365)

    for cli, g in df.groupby("cli"):
        datas = [d for d in g["data"].tolist() if isinstance(d, date)]
        ultima = max(datas) if datas else None
        dias = (anchor - ultima).days if ultima else None

        if formato == "transacional":
            mask12 = g["data"].apply(lambda d: isinstance(d, date) and d > cutoff12m)
            compras12 = int(mask12.sum())
            venda12 = float(g.loc[mask12, "val"].sum())
            datas_por_cliente[cli] = sorted(str(d) for d in datas)
        else:  # agregado / sem_data
            compras12 = 1
            venda12 = float(g["val"].sum())
            datas_por_cliente[cli] = []  # sem histórico → ciclo None → régua fixa

        snapshot.append({
            "CODCLI": cli,
            "DiasSemComprar": dias,
            "Compras12m": compras12,
            "Lucro12m": venda12,   # sem custo/lucro: usa faturamento como M
            "Venda12m": venda12,
            "UltimaCompra": str(ultima) if ultima else "",
        })
        meta[cli] = {"cliente": cli}
    return snapshot, datas_por_cliente, meta


def _pct(n: int, total: int) -> float:
    return round(n / total, 4) if total else 0.0


def analisar(df: pd.DataFrame, mapeamento: dict) -> dict:
    """Recebe o DataFrame cru + mapeamento e devolve os achados (sem cifra)."""
    limpo = _preparar(df, mapeamento)
    total = limpo["cli"].nunique()
    if total == 0:
        return {"ok": False, "erro": "Não foi possível ler clientes/valores válidos na planilha."}

    formato = _detectar_formato(limpo)
    datas_validas = [d for d in limpo["data"].tolist() if isinstance(d, date)]
    anchor = max(datas_validas) if datas_validas else date.today()

    snapshot, datas_por_cliente, meta = _build_snapshot(limpo, formato, anchor)
    modo = "personalizada" if formato == "transacional" else "fixa"
    clientes = rfm.calcular_clientes(snapshot, datas_por_cliente, meta)
    dist = rfm.agregar_distribuicoes(clientes, modo=modo)

    # Achados (percentuais e contagens — NUNCA R$).
    frases = []
    achados = {
        "ok": True,
        "formato": formato,
        "total_clientes": total,
        "data_referencia": str(anchor),
    }

    if formato != "sem_data":
        inativos60 = [c for c in clientes if (c["recencia_dias"] or 0) > INATIVO_DIAS]
        inativos90 = [c for c in clientes if (c["recencia_dias"] or 0) > 90]
        achados["pct_inativos_60d"] = _pct(len(inativos60), total)
        achados["n_inativos_60d"] = len(inativos60)
        achados["pct_inativos_90d"] = _pct(len(inativos90), total)
        frases.append(
            f"{round(achados['pct_inativos_60d']*100)}% da sua carteira "
            f"({len(inativos60)} de {total} clientes) não compram há mais de {INATIVO_DIAS} dias."
        )
        if formato == "transacional":
            urgentes = dist["regua"]["urgente"]
            achados["n_em_risco"] = urgentes
            if urgentes:
                frases.append(
                    f"{urgentes} clientes já passaram do próprio ciclo de compra e estão em risco de sumir."
                )

    # Concentração (Pareto) — também sem cifra, é um %.
    ordenados = sorted(clientes, key=lambda c: c["venda_12m"] or 0, reverse=True)
    venda_total = sum(c["venda_12m"] or 0 for c in clientes)
    if venda_total > 0:
        top_n = max(1, math.ceil(total * 0.2))
        venda_top = sum(c["venda_12m"] or 0 for c in ordenados[:top_n])
        achados["pct_faturamento_top20"] = round(venda_top / venda_total, 4)
        frases.append(
            f"Seus 20% maiores clientes concentram {round(achados['pct_faturamento_top20']*100)}% "
            f"do faturamento — atenção à dependência."
        )

    achados["segmentos"] = dist["segmentos"]
    achados["frases"] = frases
    return achados
