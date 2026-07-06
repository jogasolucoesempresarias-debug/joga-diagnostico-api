"""
Camada 1 — detecção determinística de colunas por tokens conhecidos.

Cobre os nomes de coluna típicos dos ERPs (Winthor/TOTVS/Bling) e de exports comuns.
Se achar `cliente` + `valor` com confiança, dispensa a IA e a confirmação do usuário.
"""
import unicodedata

# Ordem importa: tokens mais específicos primeiro.
TOKENS = {
    "cliente": ["codcli", "razaosocial", "nomecliente", "cliente", "razao", "fantasia", "nome", "cnpj"],
    "data_compra": ["dtultimacompra", "ultimacompra", "dtemissao", "dataemissao", "datacompra",
                     "dataped", "emissao", "data", "dt"],
    "valor": ["vltotalliquido", "vltotal", "vlrtotal", "valortotal", "faturamento", "vlfat",
              "vlvenda", "valor", "total", "venda", "receita", "monetario"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def detectar(colunas) -> dict:
    """Retorna {cliente, data_compra, valor} (valores = nome original da coluna ou None)."""
    normmap = {_norm(c): c for c in colunas}
    achado = {"cliente": None, "data_compra": None, "valor": None}
    usados = set()
    for alvo, tokens in TOKENS.items():
        for tok in tokens:
            for norm, original in normmap.items():
                if original in usados:
                    continue
                if tok in norm:
                    achado[alvo] = original
                    usados.add(original)
                    break
            if achado[alvo]:
                break
    return achado


def confiante(mapeamento: dict) -> bool:
    """Camada 1 só vale se achou cliente E valor (data é opcional)."""
    return bool(mapeamento.get("cliente") and mapeamento.get("valor"))
