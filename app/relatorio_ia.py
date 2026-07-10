"""
Relatório personalizado por IA (Fase 2a) — spec §5.3.

Segue o padrão do "Tabela Auditoria" (contratos_service.py / server.py:_gerar_ata):
OpenAI client, gpt-4.1-mini, saída em markdown (SEM response_format).

Regra de ouro (spec §2 e §5.2): entrega O QUÊ + PORQUÊ, nunca o COMO.
PROIBIDO estimar valores em R$ ou prometer resultado.
"""
import os
import logging

logger = logging.getLogger(__name__)

MODELO_OPENAI = "gpt-4.1-mini"

# Rótulos legíveis dos códigos, para a IA escrever com naturalidade.
_ROTULOS = {
    # setor
    "atacado": "Atacado distribuidor", "varejo": "Varejo / supermercado",
    "industria": "Indústria", "logistica": "Logística / transporte",
    "servicos": "Serviços", "outro": "Outro",
    # faturamento
    "ate100k": "até R$100 mil/mês", "100k_500k": "R$100–500 mil/mês",
    "500k_1mi": "R$500 mil–1 mi/mês", "1mi_2mi": "R$1–2 mi/mês",
    "2mi_5mi": "R$2–5 mi/mês", "5mi_10mi": "R$5–10 mi/mês", "mais10mi": "+R$10 mi/mês",
    # erp
    "winthor": "Winthor", "sankhya": "Sankhya", "bling": "Bling/Tiny",
    "nenhum": "sem sistema integrado",
    # urgência
    "pra_ontem": "para ontem (urgente)", "3_meses": "nos próximos 3 meses",
    "pesquisando": "sem pressa, ainda pesquisando",
}


def _rot(codigo) -> str:
    if not codigo:
        return "não informado"
    return _ROTULOS.get(codigo, str(codigo))


# Sinais concretos por resposta — o que cada resposta "fraca" revela, em linguagem de gestor.
# É isso que torna o relatório específico (a IA cita o sinal real, não um genérico).
SINAIS = {
    "q5": {"cabeca": "decide pela experiência/cabeça, sem indicadores à mão",
           "planilhas": "controla o negócio em planilhas soltas",
           "erp": "depende de relatórios avulsos do ERP, sem um painel único",
           "nao_acompanho": "não acompanha indicadores"},
    "q6": {"problema": "só olha os números quando já deu problema",
           "mes": "revisa os números apenas uma vez por mês"},
    "q7": {"dia_inteiro": "gasta cerca de um dia inteiro por semana montando planilha/relatório",
           "mais": "gasta mais de um dia por semana montando relatório na mão",
           "horas": "perde algumas horas por semana montando relatório manual"},
    "q8": {"faturamento": "acompanha só o faturamento — não enxerga margem/lucro por produto nem por cliente",
           "fat_margens": "vê a margem de apenas alguns itens, sem visão completa"},
    "q9": {"sem_metas": "trabalha sem metas definidas",
           "fim_mes": "só confere as metas no fim do mês, quando já não dá pra corrigir a rota"},
    "q10": {"nao": "não consegue ver o desempenho por vendedor/equipe",
            "esforco": "só enxerga o desempenho por vendedor com muito esforço/planilha"},
    "q11": {"nao_ideia": "não sabe quantos clientes deixaram de comprar",
            "nocao": "tem apenas uma noção vaga de quem parou de comprar"},
    "q12": {"nao": "não classifica a carteira (ativos/em risco/inativos)",
            "informal": "classifica a carteira só informalmente, sem critério"},
    "q13": {"nao_sei": "não sabe qual % da carteira está inativa",
            "mais50": "considera que mais da metade da carteira está inativa",
            "25_50": "considera que 25–50% da carteira está inativa"},
    "q14": {"nao": "não sabe quanto capital está parado em produtos sem giro",
            "estimo": "apenas estima (não sabe ao certo) o capital parado em estoque"},
    "q15": {"sempre": "sofre ruptura de itens importantes com frequência",
            "as_vezes": "tem ruptura de itens importantes de vez em quando"},
    "q16": {"feeling": "faz as compras no feeling, sem giro/cobertura",
            "misto": "compra meio no feeling, meio no dado"},
}

# Padrão do setor por área (comparação, nunca cifra).
BENCH = {
    "Dados": "empresas organizadas acompanham os indicadores num painel único e atualizado, sem depender de planilha manual",
    "Comercial": "o padrão é acompanhar margem por produto e por cliente, metas em tempo real e ranking por vendedor",
    "Carteira": "o padrão é classificar a carteira e agir sobre quem está sumindo antes de perder o cliente de vez",
    "Estoque": "o padrão é comprar por giro e cobertura, sabendo o capital parado e antecipando a ruptura",
}

AREA_QUESTIONS = {
    "Dados": ["q5", "q6", "q7"], "Comercial": ["q8", "q9", "q10"],
    "Carteira": ["q11", "q12", "q13"], "Estoque": ["q14", "q15", "q16"],
}


PROMPT_SISTEMA = """Você é o analista de diagnóstico da JOGA Soluções Empresariais, uma consultoria \
que organiza dados, automação, IA e gestão para pequenas e médias empresas.

Escreva um diagnóstico CURTO, ESPECÍFICO e PERSONALIZADO. O gestor tem que ler e pensar "isso é a MINHA
empresa, eles entenderam o meu caso" — jamais um texto que serviria para qualquer um.

REGRA-MESTRA: apoie CADA afirmação nos SINAIS concretos que a pessoa respondeu (seção EVIDÊNCIAS abaixo).
Cite-os quase literalmente. É PROIBIDO escrever frase genérica de consultoria (ex.: "ter dados é importante",
"no mercado competitivo de hoje", "a gestão eficiente é fundamental"). Se uma frase serviria para qualquer
empresa, corte-a.

Para CADA área Crítica ou em Atenção (na ordem dada), escreva um parágrafo curto que:
1. Diga o que a pessoa FAZ HOJE, citando o(s) sinal(is) concreto(s) dela.
2. Mostre a CONSEQUÊNCIA prática disso no dia a dia (o porquê dói de verdade) — concreto, sem cifra.
3. Faça o CONTRASTE direto com o padrão do setor fornecido ("empresas organizadas fazem Y; você ainda não").

TERMINANTEMENTE PROIBIDO:
- Nenhum valor em R$ (nada de "você perde R$ X"). Zero cifras.
- Não prometa resultado ("vamos aumentar X%").
- Não entregue o COMO (a solução/o passo a passo) — isso é o produto pago, fica para a call.

FORMATO (markdown, 350–450 palavras):
- Título com o nome da empresa e o setor.
- 1 parágrafo de abertura curto que cite a dor declarada com as palavras dela.
- 1 seção por área crítica/atenção: "### Área — Nível", com o parágrafo acima.
- Fechamento: UMA frase dizendo por qual área começar e por quê. Este relatório é INTERNO da equipe JOGA
  (não é enviado ao cliente), então NÃO escreva convite para conversa, "vamos conversar?", "retornamos em
  48h" nem qualquer chamada dirigida ao cliente. Termine no diagnóstico."""


def _evidencias(respostas: dict, resultado: dict) -> str:
    """Monta, por área (oportunidades primeiro), os sinais concretos + o padrão do setor."""
    placar = resultado.get("placar", {})
    ordem = [o["area"] for o in resultado.get("oportunidades", [])]
    for a in placar:
        if a not in ordem:
            ordem.append(a)

    blocos = []
    for area in ordem:
        nivel = placar.get(area)
        sinais = []
        for q in AREA_QUESTIONS.get(area, []):
            frase = SINAIS.get(q, {}).get(respostas.get(q))
            if frase:
                sinais.append(frase)
        linhas = "\n".join(f"    - {s}" for s in sinais) or "    - (sem fraquezas relevantes nesta área)"
        blocos.append(f"  {area} [{nivel}]:\n{linhas}\n    padrão do setor: {BENCH.get(area, '')}")
    return "\n".join(blocos)


def _montar_contexto(contato: dict, respostas: dict, resultado: dict) -> str:
    dor = contato.get("desafio") or "não declarada"
    return f"""DADOS DO LEAD
Empresa: {contato.get('empresa')}
Setor: {_rot(contato.get('setor'))}
Porte (faturamento): {_rot(contato.get('faturamento'))}
ERP atual: {_rot(contato.get('erp'))}
Urgência: {_rot(contato.get('urgencia'))}
Dor declarada pelo gestor (use as palavras dela): "{dor}"

EVIDÊNCIAS POR ÁREA (sinais reais das respostas — use-os, não invente outros):
{_evidencias(respostas, resultado)}

Escreva o diagnóstico seguindo as regras. Foque nas áreas Crítico/Atenção e cite os sinais concretos acima."""


def _stub(contato: dict, resultado: dict) -> str:
    """Relatório de fallback quando não há chave de IA (dev)."""
    placar = resultado.get("placar", {})
    linhas = "\n".join(f"- **{a}:** {n}" for a, n in placar.items())
    oport = "\n".join(f"- {o['titulo']}" for o in resultado.get("oportunidades", []))
    return (
        f"# Diagnóstico JOGA — {contato.get('empresa', '')}\n\n"
        f"_(Relatório gerado em modo de desenvolvimento — sem IA.)_\n\n"
        f"## Placar de maturidade\n{linhas}\n\n"
        f"## Oportunidades prioritárias\n{oport}\n\n"
        f"Fale com a JOGA — retorno em até 48h."
    )


def gerar(contato: dict, respostas: dict, resultado: dict) -> str:
    """
    Gera o relatório completo em markdown. Se não houver OPENAI_API_KEY,
    devolve um stub e loga (não quebra o /submit).
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY ausente — usando relatório stub (dev).")
        return _stub(contato, resultado)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=MODELO_OPENAI,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": _montar_contexto(contato, respostas, resultado)},
            ],
            max_tokens=2500,
            temperature=0.4,
        )
        return resp.choices[0].message.content
    except Exception as e:  # noqa: BLE001 — não deixar a IA derrubar o fluxo
        logger.error(f"Falha ao gerar relatório por IA: {e}")
        return _stub(contato, resultado)
