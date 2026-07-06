"""
Camada 2 — mapeamento de colunas por IA (gpt-4.1-mini).

Manda cabeçalho + amostra de linhas como TEXTO (barato) e pede um JSON
{cliente, data_compra, valor} com o nome exato das colunas. Segue o padrão
de `Tabela Auditoria/contratos_service.py` (response_format json_object + guard de chave).
Retorna None se não houver chave ou a IA falhar → o leitor cai no fallback do modelo.
"""
import json
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

MODELO_OPENAI = "gpt-4.1-mini"

PROMPT_SISTEMA = """Você recebe o cabeçalho e algumas linhas de uma planilha de vendas exportada de um ERP.
Sua tarefa é identificar quais colunas correspondem a:
- "cliente": o nome ou código que identifica o CLIENTE (razão social, nome, código do cliente, CNPJ).
- "data_compra": a data da compra/emissão/última compra (se não existir, use null).
- "valor": o valor monetário da venda/faturamento (total, valor, faturamento).

Responda SOMENTE com um JSON válido nesta estrutura, usando EXATAMENTE os nomes das colunas como aparecem no cabeçalho:
{"cliente": "<nome da coluna ou null>", "data_compra": "<nome da coluna ou null>", "valor": "<nome da coluna ou null>"}"""


def mapear(df: pd.DataFrame, max_linhas: int = 5) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY ausente — mapeador_ia indisponível (cai no modelo).")
        return None

    colunas = list(df.columns)
    amostra = df.head(max_linhas).to_csv(index=False)
    conteudo = f"CABEÇALHO: {colunas}\n\nAMOSTRA (CSV):\n{amostra}"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=MODELO_OPENAI,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": conteudo},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0,
        )
        dados = json.loads(resp.choices[0].message.content)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Falha no mapeador_ia: {e}")
        return None

    # Só aceita colunas que existem de fato na planilha.
    mapeamento = {}
    for alvo in ("cliente", "data_compra", "valor"):
        col = dados.get(alvo)
        mapeamento[alvo] = col if (col in colunas) else None
    return mapeamento
