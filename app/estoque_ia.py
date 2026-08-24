"""
Análise por IA do diagnóstico de ESTOQUE (LP) — o texto que o VISITANTE lê na tela.

Diferença importante para o `relatorio_ia.py`: aquele relatório é INTERNO (vai no e-mail da
equipe). Este é escrito PARA o cliente, que o lê logo depois de deixar o contato. Muda o tom
(2ª pessoa), muda o tamanho (cabe num card, não numa página) e continua valendo a regra dura:

  ⚠️ NENHUM valor em R$. Nunca. A entrada do modelo são 12 respostas em escala; ele NÃO tem o
  estoque, o giro nem o faturamento de ninguém. Qualquer cifra que ele escrever é invenção —
  e inventar número numa página cuja tese é "não é promessa, é prova" é o pior erro possível.
  Além do prompt, há uma varredura determinística em `_sem_cifras()` como segunda trava.

Saída em JSON de formato fixo (leitura / pontos / fecho) em vez de prosa livre: o layout do
card fica previsível e o modelo tem menos espaço para divagar.
"""
import json
import logging
import os
import re

logger = logging.getLogger("diagnostico.estoque_ia")

MODELO_OPENAI = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

PROMPT_SISTEMA = """Você é o analista de estoque e compras da JOGA Soluções Empresariais.

Um gestor acabou de responder um questionário curto sobre a gestão de estoque da empresa dele.
Escreva a leitura que ELE vai ler na tela, agora. Fale com ele (você/sua empresa), não sobre ele.

REGRA-MESTRA: cada afirmação tem que se apoiar numa resposta concreta que ele deu (seção
EVIDÊNCIAS). Cite o que ele respondeu quase literalmente. Se uma frase serviria para qualquer
empresa do país, corte-a. Nada de "no mercado competitivo de hoje" ou "a gestão eficiente é
fundamental".

A CONSEQUÊNCIA PRECISA SER UMA CENA, NÃO UM CONCEITO. Descreva o que acontece no galpão, na
mesa do comprador ou no telefone — não o efeito abstrato. Compare:
  ✗ "Isso dificulta o controle e compromete a gestão diária." (não diz nada)
  ✗ "Pode levar a compras descoordenadas, afetando a disponibilidade." (hedge + abstrato)
  ✓ "O item furou e você descobre pelo vendedor, quando o cliente já pediu e não tinha."
  ✓ "O comprador repete o pedido do mês passado porque é o único número que ele tem na mão."

PROIBIDO hedge: nada de "pode levar", "pode resultar", "pode comprometer", "tende a". Se você
não tem certeza suficiente para afirmar, não escreva a frase. Fale no presente do indicativo.

TERMINANTEMENTE PROIBIDO:
- Qualquer valor em dinheiro. Zero cifras, zero "R$", zero percentuais de perda estimados,
  zero "você pode estar perdendo X". Você NÃO tem os dados dele: só as respostas do
  questionário. Inventar número aqui destrói a credibilidade da análise inteira.
- Prometer resultado ("vamos reduzir sua ruptura em X%").
- Entregar o passo a passo da solução. Diga O QUE está frágil e POR QUE isso dói na operação;
  o COMO é o trabalho da JOGA e fica para a conversa.
- Elogio vazio. Se ele respondeu bem numa área, reconheça em meia frase e siga.

CONTEXTO ÚTIL: quem controla estoque bem trabalha com cobertura em dias (não em quantidade),
acompanha ruptura por comprador e por curva ABC, define cobertura-alvo e lead time real por
fornecedor, trata validade por lote com plano de ação, e recebe os alertas sem precisar ir
procurar. Use esse padrão como contraste quando ele não fizer algo disso.

Responda SOMENTE com um JSON válido, sem markdown, neste formato exato:
{
  "leitura": "2 ou 3 frases lendo a operação INTEIRA. Se ele respondeu SIM em alguma coisa, comece reconhecendo isso em meia frase (citando qual) e vire com um 'mas'. Não repita o conteúdo dos pontos abaixo.",
  "pontos": [
    {"titulo": "nome curto do ponto (3 a 6 palavras)",
     "texto": "2 a 3 frases: o que ele faz hoje (citando a resposta dele) e a consequência prática disso na operação. Sem cifra, sem solução."}
  ],
  "fecho": "1 frase dizendo por onde começar e por quê."
}

São de 2 a 4 pontos, do mais grave para o menos grave, na ordem das áreas fracas que eu passar.
Cada texto de ponto: no máximo 55 palavras.

SE EU DISSER QUE NÃO HÁ ÁREA FRACA: não invente defeito. É PROIBIDO usar a construção "você faz
X, MAS mesmo assim tem problema Y" para manufaturar uma dor que as respostas não mostram. Nesse
caso, reconheça o nível da operação em 2 frases e use os pontos para o que vem DEPOIS de ter o
básico no lugar (aprofundar por curva ABC, sazonalidade, política de estoque por classe,
acompanhamento por comprador). Enquadre como evolução, não como falha."""


def _rot(v) -> str:
    return str(v) if v not in (None, "") else "—"


def _evidencias(respostas: dict, perguntas_texto: dict, resultado: dict) -> str:
    """Lista pergunta → resposta em português, para o modelo citar em vez de inventar."""
    rot = {"sim": "SIM", "mais_ou_menos": "só em parte", "nao": "NÃO"}
    linhas = []
    for codigo, texto in perguntas_texto.items():
        r = respostas.get(codigo)
        if r:
            linhas.append(f"- {texto} → {rot.get(r, r)}")

    placar = resultado.get("placar", {})
    niveis = "\n".join(f"- {area}: {nivel}" for area, nivel in placar.items())
    fracas = ", ".join(o["area"] for o in resultado.get("oportunidades", []))

    if resultado.get("maduro"):
        instrucao = (
            "ÁREAS FRACAS: NENHUMA. Esta operação já tem o básico no lugar. "
            "NÃO invente defeito e NÃO use 'mas mesmo assim'. Reconheça o nível e trate os "
            "pontos como próximo passo de evolução."
        )
    else:
        instrucao = f"ÁREAS FRACAS, NESTA ORDEM: {fracas}"

    return (
        f"EVIDÊNCIAS (o que ele respondeu)\n{chr(10).join(linhas)}\n\n"
        f"PLACAR CALCULADO\n{niveis}\n\n{instrucao}"
    )


def _montar_contexto(contato: dict, respostas: dict, perguntas_texto: dict, resultado: dict) -> str:
    return (
        f"EMPRESA: {_rot(contato.get('empresa'))}\n"
        f"SETOR: {_rot(contato.get('setor'))}\n"
        f"FAIXA DE SKUs: {_rot(contato.get('skus'))}\n"
        f"ERP: {_rot(contato.get('erp'))}\n\n"
        + _evidencias(respostas, perguntas_texto, resultado)
    )


# Segunda trava contra cifra inventada — o prompt proíbe, isto verifica.
_CIFRA = re.compile(r"(R\$|\breais\b|\bmilh(ão|ões)\b|\bmil reais\b)", re.IGNORECASE)


def _sem_cifras(analise: dict) -> dict:
    """Remove qualquer ponto que tenha escapado com valor em dinheiro e loga o incidente."""
    def limpo(txt: str) -> bool:
        return not _CIFRA.search(txt or "")

    if not limpo(analise.get("leitura", "")) or not limpo(analise.get("fecho", "")):
        logger.error("IA de estoque devolveu cifra em leitura/fecho — caindo para o stub.")
        return {}

    pontos = [p for p in analise.get("pontos", []) if limpo(p.get("titulo")) and limpo(p.get("texto"))]
    if len(pontos) != len(analise.get("pontos", [])):
        logger.error("IA de estoque devolveu cifra em ponto(s) — removidos.")
    analise["pontos"] = pontos
    return analise if pontos else {}


def _stub(resultado: dict) -> dict:
    """Sem OPENAI_API_KEY (dev) ou falha na IA: devolve algo útil a partir do placar."""
    area_dor = resultado.get("maior_dor", {}).get("area", "onde o placar está mais fraco")

    # Placar todo Maduro: o stub também não pode inventar defeito (mesma regra do prompt).
    if resultado.get("maduro"):
        return {
            "leitura": (
                "Pelas suas respostas, o básico da gestão de estoque já está no lugar: os "
                "controles que a maioria das operações não tem, a sua tem."
            ),
            "pontos": [
                {
                    "titulo": "Próximo passo",
                    "texto": (
                        "Com o básico de pé, o ganho passa a vir do refino: política de estoque "
                        "por curva, sazonalidade e acompanhamento individual por comprador."
                    ),
                }
            ],
            "fecho": f"Aprofundaria por {area_dor}.",
        }

    return {
        "leitura": (
            "Pelas suas respostas, a leitura completa da sua operação depende de alguns "
            "controles que ainda não estão de pé."
        ),
        "pontos": [
            {"titulo": o["area"], "texto": o["titulo"]}
            for o in resultado.get("oportunidades", [])[:4]
        ],
        "fecho": f"Começaria por {area_dor}.",
    }


def gerar(contato: dict, respostas: dict, perguntas_texto: dict, resultado: dict) -> dict:
    """
    Devolve {"leitura": str, "pontos": [{"titulo","texto"}], "fecho": str}.
    Nunca levanta exceção: qualquer falha vira stub, para não derrubar o endpoint.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY ausente — análise de estoque em stub (dev).")
        return _stub(resultado)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=MODELO_OPENAI,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": _montar_contexto(contato, respostas, perguntas_texto, resultado)},
            ],
            response_format={"type": "json_object"},
            max_tokens=1200,
            temperature=0.4,
        )
        analise = json.loads(resp.choices[0].message.content)
        analise = _sem_cifras(analise)
        return analise or _stub(resultado)
    except Exception as e:  # noqa: BLE001 — IA nunca derruba o fluxo
        logger.error(f"Falha na análise de estoque por IA: {e}")
        return _stub(resultado)
