"""
Scoring do diagnóstico de ESTOQUE (LP /solucoes/gestao-de-estoque) — puro, testável, sem IA.

Espelha o `scoring.py` do diagnóstico geral em contrato e formato de saída, mas com
questionário e áreas próprios. Os dois convivem: o geral mede 5 áreas do negócio
(Dados/Comercial/Financeiro/Clientes/Estoque); este abre a caixa do Estoque em 5 áreas.

As áreas são as MESMAS que a LP apresenta como pilares, de propósito: o visitante lê os
quatro pilares ("quanto está parado?", "o que vai faltar?", "o que vai vencer?", "o que
comprar?") e recebe o placar dele nessas mesmas quatro perguntas — mais Acompanhamento,
que é o bloco do "consultor conectado".

Contrato de entrada: `respostas` = {codigo_pergunta: codigo_opcao}, com opções
sim / mais_ou_menos / nao. Resposta ausente ou desconhecida vale 0 (degradação segura).
Saída: mesmo shape do scoring geral, para reusar prebrief.enviar_equipe sem adaptação.

NENHUM valor em R$ — nem aqui, nem no relatório. Ver estoque_ia.py.
"""

AREA_PARADO = "Capital parado"
AREA_RUPTURA = "Ruptura"
AREA_VALIDADE = "Validade"
AREA_COMPRAS = "Compras"
AREA_ACOMPANHAMENTO = "Acompanhamento"

AREAS = [AREA_PARADO, AREA_RUPTURA, AREA_VALIDADE, AREA_COMPRAS, AREA_ACOMPANHAMENTO]

# Desempate quando duas áreas empatam em fraqueza: primeiro o que dói mais rápido no caixa.
PRIORIDADE = [AREA_PARADO, AREA_RUPTURA, AREA_COMPRAS, AREA_VALIDADE, AREA_ACOMPANHAMENTO]

# Escala única: as 12 perguntas são todas "você faz isso hoje?".
ESCALA = {"sim": 2, "mais_ou_menos": 1, "nao": 0}

# Pergunta → área. A ordem aqui é a ordem em que a LP mostra as perguntas.
PERGUNTAS = {
    "e1": AREA_PARADO,          # sabe quanto está parado acima da necessidade
    "e2": AREA_PARADO,          # identifica produtos há muitos dias sem venda
    "e3": AREA_RUPTURA,         # acompanha % de ruptura
    "e4": AREA_RUPTURA,         # ruptura por comprador e por curva ABC
    "e5": AREA_VALIDADE,        # identifica antecipadamente o que vai vencer
    "e6": AREA_VALIDADE,        # sabe quanto perdeu por vencimento em 12 meses
    "e7": AREA_COMPRAS,         # cobertura-alvo definida
    "e8": AREA_COMPRAS,         # lead time real acompanhado
    "e9": AREA_COMPRAS,         # orçamento estruturado de compras
    "e10": AREA_COMPRAS,        # sugestão de compras por parâmetros
    "e11": AREA_ACOMPANHAMENTO, # relatórios/alertas chegam sozinhos ao responsável
    "e12": AREA_ACOMPANHAMENTO, # meta de ruptura e de compras por comprador
}

# O "problema" que a área revela — vira título de oportunidade no placar e no pré-brief.
TITULOS = {
    AREA_PARADO: "Capital parado sem nome: não se sabe onde o dinheiro está preso",
    AREA_RUPTURA: "Ruptura percebida tarde: a venda já foi perdida quando aparece",
    AREA_VALIDADE: "Validade tratada como relatório, não como risco antecipado",
    AREA_COMPRAS: "Compra por percepção: sem cobertura-alvo, lead time real nem orçamento",
    AREA_ACOMPANHAMENTO: "Ninguém é avisado: o problema espera alguém ir procurar",
}

# Gancho de conversa por área — o que a JOGA mostra primeiro numa call sobre essa dor.
ANCORAS = {
    AREA_PARADO: "Capital parado por produto, fornecedor e comprador",
    AREA_RUPTURA: "Ruptura por comprador e curva ABC + meta de ruptura",
    AREA_VALIDADE: "Validade por lote (FEFO) com plano de ação",
    AREA_COMPRAS: "Sugestão de compra por cobertura-alvo + orçamento por comprador",
    AREA_ACOMPANHAMENTO: "Relatórios agendados por carteira + alerta de cobertura",
}


def _nivel(fracao: float) -> str:
    """Mesmos cortes do scoring geral, para os dois placares falarem a mesma língua."""
    if fracao < 0.34:
        return "Crítico"
    if fracao < 0.60:
        return "Atenção"
    if fracao < 0.85:
        return "Bom"
    return "Maduro"


def _fracao_area(area: str, respostas: dict) -> float:
    perguntas = [q for q, a in PERGUNTAS.items() if a == area]
    if not perguntas:
        return 0.0
    maximo = len(perguntas) * max(ESCALA.values())
    soma = sum(ESCALA.get(respostas.get(q), 0) for q in perguntas)
    return soma / maximo


def resumo_respostas(respostas: dict) -> dict:
    """Contagem crua — alimenta o placar da tela e o texto do pré-brief."""
    respostas = respostas or {}
    validas = [respostas.get(q) for q in PERGUNTAS]
    return {
        "sim": sum(1 for v in validas if v == "sim"),
        "parcial": sum(1 for v in validas if v == "mais_ou_menos"),
        "nao": sum(1 for v in validas if v == "nao"),
        "respondidas": sum(1 for v in validas if v in ESCALA),
        "total": len(PERGUNTAS),
    }


def calcular(respostas: dict) -> dict:
    """
    Retorna o mesmo shape do scoring geral — placar / fracoes / oportunidades / maior_dor —
    para que prebrief.enviar_equipe e os e-mails funcionem sem nenhuma adaptação.
    """
    respostas = respostas or {}

    fracoes = {area: _fracao_area(area, respostas) for area in AREAS}
    placar = {area: _nivel(f) for area, f in fracoes.items()}

    ordenadas = sorted(AREAS, key=lambda a: (fracoes[a], PRIORIDADE.index(a)))

    # Oportunidades = todas as áreas em Crítico/Atenção, a mais fraca primeiro.
    # Se nenhuma estiver fraca, aponta a mais fraca mesmo assim (sempre há por onde evoluir).
    # Áreas realmente fracas. Pode ser LISTA VAZIA — e isso é uma informação, não um problema
    # a ser contornado: quem respondeu bem em tudo não pode receber dor fabricada. Antes daqui
    # havia um `or ordenadas[:1]` que entregava uma "área fraca" mesmo para o placar todo
    # Maduro, e a IA obedientemente inventava um defeito. Numa página cuja tese é "não é
    # promessa, é prova", inventar dor é o pior erro possível.
    fracas = [a for a in ordenadas if placar[a] in ("Crítico", "Atenção")]
    maduro = not fracas

    # Acompanhamento vai para o fim da lista: a narrativa fecha melhor em "e ninguém te avisa
    # de nada disso" do que abre por aí. As dores substantivas lideram.
    fracas = [a for a in fracas if a != AREA_ACOMPANHAMENTO] + [
        a for a in fracas if a == AREA_ACOMPANHAMENTO
    ]
    oportunidades = [{"area": a, "titulo": TITULOS[a]} for a in fracas]

    # Âncora = o gancho da conversa de vendas (vai no WhatsApp do pré-brief).
    #
    # Acompanhamento é meta-área: mede como a pessoa fica sabendo, não o que está errado no
    # estoque. Tem só duas perguntas e as duas são "você recebe alerta?", então zera fácil e
    # sequestraria a âncora quase sempre. Por isso as substantivas têm preferência — mas só
    # quando alguma delas está de fato fraca. Se o único problema é o acompanhamento, a âncora
    # é o acompanhamento; apontar "capital parado" numa operação Madura nisso manda a equipe
    # para a call falando de um problema que o cliente não tem.
    fracas_substantivas = [a for a in fracas if a != AREA_ACOMPANHAMENTO]
    if fracas_substantivas:
        dor = fracas_substantivas[0]
    elif fracas:
        dor = fracas[0]
    else:
        dor = ordenadas[0]  # tudo maduro → aponta o ponto mais fraco como aprofundamento
    return {
        "placar": placar,
        "fracoes": fracoes,
        "oportunidades": oportunidades,
        "maduro": maduro,   # nenhuma área em Crítico/Atenção — a IA NÃO deve inventar dor
        "maior_dor": {"area": dor, "titulo": TITULOS[dor], "ancora": ANCORAS[dor]},
        "resumo": resumo_respostas(respostas),
    }


def desafio_sintetico(resultado: dict) -> str:
    """
    O questionário de estoque não tem campo aberto de dor. Para o pré-brief não sair com
    "(não declarada)", sintetiza a dor a partir do próprio placar.
    """
    fracas = [o["area"] for o in resultado.get("oportunidades", [])]
    if not fracas:
        return "Gestão de estoque já estruturada — busca aprofundamento"
    if len(fracas) == 1:
        return f"Ponto frágil: {fracas[0]}"
    return f"{len(fracas)} áreas pedindo atenção: " + ", ".join(fracas)
