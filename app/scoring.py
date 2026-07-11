"""
Scoring de maturidade (Fase 2a) — puro, testável, sem IA.

Mapeia as respostas do questionário (spec §4) em um nível por área
(Crítico · Atenção · Bom · Maduro) e devolve o placar + as 3 oportunidades
(áreas mais fracas) + a maior dor (para o pré-brief). NENHUM valor em R$.

Contrato de entrada: `respostas` é um dict {codigo_pergunta: codigo_opcao}.
Os códigos são os documentados em schemas.py / README (ex.: q5="planilhas").
Respostas ausentes/desconhecidas valem 0 ponto (degradação segura).
"""
from typing import Optional

# Nomes de exibição das áreas (chaves do placar)
AREA_DADOS = "Dados"
AREA_COMERCIAL = "Comercial"
AREA_FINANCEIRO = "Financeiro"
AREA_CARTEIRA = "Gestão de Clientes"
AREA_ESTOQUE = "Estoque"

# Ordem de prioridade para desempate (dor mais estratégica primeiro)
PRIORIDADE = [AREA_CARTEIRA, AREA_FINANCEIRO, AREA_COMERCIAL, AREA_DADOS, AREA_ESTOQUE]

# Pontuação por resposta (maior = mais maduro). Ver spec §4/§5.1.
PONTOS = {
    AREA_DADOS: {
        "q5": {"cabeca": 0, "planilhas": 1, "erp": 2, "bi": 3, "nao_acompanho": 0},
        "q6": {"dia": 3, "semana": 2, "mes": 1, "problema": 0, "nao_olho": 0},
        "q7": {"quase_nada": 3, "horas": 2, "dia_inteiro": 1, "mais": 0, "nao_sei": 0},
    },
    AREA_COMERCIAL: {
        "q8": {"faturamento": 0, "fat_margens": 1, "margem_completa": 2, "nao_acompanho": 0},
        "q9": {"sem_metas": 0, "fim_mes": 1, "de_perto": 2},
        "q10": {"nao": 0, "esforco": 1, "facil": 2},
    },
    AREA_FINANCEIRO: {
        "q19": {"lucro_exato": 2, "lucro_estimo": 1, "lucro_faturamento": 0},
        # "não vendo a prazo" = sem risco de inadimplência → nota cheia (não penaliza caixa/à vista).
        "q20": {"inad_controlo": 2, "inad_nocao": 1, "inad_nao": 0, "inad_nao_prazo": 2},
        "q21": {"dre_mes": 2, "dre_as_vezes": 1, "dre_nunca": 0},
    },
    AREA_CARTEIRA: {
        "q11": {"nao_ideia": 0, "nocao": 1, "exato": 2},
        "q12": {"nao": 0, "informal": 1, "formal": 2},
        # Q13 mede maturidade pela consciência do número, não pela faixa em si.
        "q13": {"menos10": 2, "10_25": 2, "25_50": 2, "mais50": 2, "nao_sei": 0},
    },
    AREA_ESTOQUE: {
        "q14": {"nao": 0, "estimo": 1, "exato": 2},
        "q15": {"sempre": 0, "as_vezes": 1, "raramente": 2},
        "q16": {"feeling": 0, "misto": 1, "dados": 2},
    },
}

# Títulos das oportunidades (o "problema" que a área revela)
TITULOS = {
    AREA_DADOS: "Decisão sem dados: indicadores na cabeça e na planilha",
    AREA_COMERCIAL: "Comercial no escuro: sem visão de margem, metas e vendedor",
    AREA_FINANCEIRO: "Financeiro no escuro: lucro real, caixa e inadimplência sem controle",
    AREA_CARTEIRA: "Sua base de clientes some e ninguém percebe",
    AREA_ESTOQUE: "Estoque no feeling: capital parado e ruptura",
}

# Solução âncora sugerida por área (para o pré-brief §7)
ANCORAS = {
    AREA_DADOS: "Painel de Indicadores (BI)",
    AREA_COMERCIAL: "Gestão de Vendas",
    AREA_FINANCEIRO: "Resultado Gerencial (DRE) + IA",
    AREA_CARTEIRA: "Gestão de Clientes",
    AREA_ESTOQUE: "Gestão de Estoque",
}


def _nivel(fracao: float) -> str:
    if fracao < 0.34:
        return "Crítico"
    if fracao < 0.60:
        return "Atenção"
    if fracao < 0.85:
        return "Bom"
    return "Maduro"


def _fracao_area(area: str, respostas: dict) -> float:
    """Soma os pontos das perguntas da área / máximo possível da área."""
    perguntas = PONTOS[area]
    soma = 0
    maximo = 0
    for pergunta, opcoes in perguntas.items():
        maximo += max(opcoes.values())
        resposta = respostas.get(pergunta)
        soma += opcoes.get(resposta, 0)
    return (soma / maximo) if maximo else 0.0


def _estoque_se_aplica(setor: Optional[str]) -> bool:
    """Serviços (sem estoque) não entram na área de Estoque."""
    return (setor or "").strip().lower() != "servicos"


def calcular(respostas: dict, setor: Optional[str] = None) -> dict:
    """
    Retorna:
      {
        "placar": {area: nivel, ...},           # só áreas aplicáveis
        "fracoes": {area: float, ...},
        "oportunidades": [{"area","titulo"}, ...],   # 3 áreas mais fracas
        "maior_dor": {"area","titulo","ancora"},
      }
    """
    respostas = respostas or {}
    areas = [AREA_DADOS, AREA_COMERCIAL, AREA_FINANCEIRO, AREA_CARTEIRA]
    if _estoque_se_aplica(setor):
        areas.append(AREA_ESTOQUE)

    fracoes = {area: _fracao_area(area, respostas) for area in areas}
    placar = {area: _nivel(f) for area, f in fracoes.items()}

    # Ordena por fração (mais fraco primeiro); desempata pela PRIORIDADE.
    ordenadas = sorted(areas, key=lambda a: (fracoes[a], PRIORIDADE.index(a)))

    oportunidades = [{"area": a, "titulo": TITULOS[a]} for a in ordenadas[:3]]
    dor = ordenadas[0]
    maior_dor = {"area": dor, "titulo": TITULOS[dor], "ancora": ANCORAS[dor]}

    return {
        "placar": placar,
        "fracoes": fracoes,
        "oportunidades": oportunidades,
        "maior_dor": maior_dor,
    }
