"""
Orquestrador da leitura de planilha (Fase 2b) — as 3 camadas.

1. parsers_erp.detectar (tokens conhecidos) → se achar cliente+valor, analisa direto.
2. mapeador_ia.mapear (gpt-4.1-mini) → propõe mapeamento; front confirma antes de analisar.
3. fallback: pedir o modelo (`/api/diagnostico/modelo`).

LGPD: tudo em memória — o arquivo NUNCA é gravado em disco. Só os `achados` saem daqui.
"""
import io
import logging

import pandas as pd

from . import analise, mapeador_ia, parsers_erp

logger = logging.getLogger(__name__)


def _ler_df(conteudo: bytes, filename: str) -> pd.DataFrame:
    """Leitura tolerante: xlsx (openpyxl) ou CSV (`;`/`,`, utf-8-sig). Tudo como string."""
    nome = (filename or "").lower()
    buf = io.BytesIO(conteudo)

    if nome.endswith((".csv", ".txt")):
        for sep in (";", ","):
            try:
                buf.seek(0)
                df = pd.read_csv(buf, sep=sep, encoding="utf-8-sig", dtype=str)
                if df.shape[1] >= 2:
                    return df
            except Exception:  # noqa: BLE001
                continue
        raise ValueError("CSV ilegível (separador/codificação).")

    # Excel
    try:
        buf.seek(0)
        return pd.read_excel(buf, dtype=str, engine="openpyxl")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Arquivo não parece uma planilha válida (.xlsx/.csv): {e}")


def ler(conteudo: bytes, filename: str, mapeamento_confirmado: dict | None = None) -> dict:
    """
    Retorna:
      - {ok:True, achados:{...}, mapeamento:{...}}                         → analisou
      - {ok:True, precisa_confirmar:True, mapeamento, colunas, amostra}    → front confirma e re-chama
      - {ok:False, fallback_modelo:True, erro}                             → não deu; usa o modelo
    """
    try:
        df = _ler_df(conteudo, filename)
    except ValueError as e:
        return {"ok": False, "fallback_modelo": True, "erro": str(e)}

    if df.empty or df.shape[1] < 2:
        return {"ok": False, "fallback_modelo": True, "erro": "Planilha vazia ou sem colunas suficientes."}

    # Re-chamada após confirmação do usuário.
    if mapeamento_confirmado:
        achados = analise.analisar(df, mapeamento_confirmado)
        return {"ok": achados.get("ok", False), "achados": achados, "mapeamento": mapeamento_confirmado}

    # Camada 1 — determinística.
    m1 = parsers_erp.detectar(df.columns)
    if parsers_erp.confiante(m1):
        achados = analise.analisar(df, m1)
        return {"ok": achados.get("ok", False), "achados": achados, "mapeamento": m1}

    # Camada 2 — IA (precisa confirmar).
    m2 = mapeador_ia.mapear(df)
    if m2 and m2.get("cliente") and m2.get("valor"):
        return {
            "ok": True,
            "precisa_confirmar": True,
            "mapeamento": m2,
            "colunas": list(df.columns),
            "amostra": df.head(3).fillna("").astype(str).values.tolist(),
        }

    # Camada 3 — fallback do modelo.
    return {
        "ok": False,
        "fallback_modelo": True,
        "erro": "Não consegui identificar as colunas de cliente e valor. Baixe o modelo e preencha.",
    }
