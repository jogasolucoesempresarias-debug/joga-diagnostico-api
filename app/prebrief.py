"""
Pré-brief + notificações do Diagnóstico JOGA.

Decisão de produto: a JOGA recebe TUDO e é quem contata o cliente.
- **Equipe JOGA:** 1 e-mail (pré-brief + relatório completo + achados) + 1 WhatsApp (pré-brief).
- **Cliente:** 1 e-mail curto de "recebido" (gated por AVISO_CLIENTE_ATIVO). **SEM WhatsApp pro
  cliente** por ora — não usar o número do DanfeZap; aguardando a instância UazAPI da JOGA.

Flags:
- ENVIO_ATIVO (mestra): false = só loga, não dispara nada.
- AVISO_CLIENTE_ATIVO: gate extra do e-mail pro cliente (default false).

Chamados via BackgroundTasks para a resposta ser rápida.
"""
import html as _html
import logging
import re

from .config import config
from .services import email_service
from .services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)

_AMBER = "#f4a52a"
_INK = "#13171e"
_CREAM = "#f5f2ec"

_ROTULOS = {
    "atacado": "Atacado distribuidor", "varejo": "Varejo / supermercado",
    "industria": "Indústria", "logistica": "Logística / transporte",
    "servicos": "Serviços", "outro": "Outro",
    "ate100k": "até R$100 mil/mês", "100k_500k": "R$100–500 mil/mês",
    "500k_2mi": "R$500 mil–2 mi/mês", "2mi_10mi": "R$2–10 mi/mês", "mais10mi": "+R$10 mi/mês",
    "winthor": "Winthor", "totvs": "TOTVS", "bling": "Bling/Tiny", "nenhum": "sem sistema integrado",
    "pra_ontem": "Pra ontem", "3_meses": "Nos próximos 3 meses", "pesquisando": "Pesquisando",
}


def _rot(codigo) -> str:
    if not codigo:
        return "não informado"
    return _ROTULOS.get(codigo, str(codigo))


def montar_texto(contato: dict, resultado: dict, tem_planilha: bool = False) -> str:
    """Texto do pré-brief no formato da spec §7."""
    placar = resultado.get("placar", {})
    dor_area = resultado.get("maior_dor", {}).get("area", "")
    linhas_placar = []
    for area, nivel in placar.items():
        marca = "   ← maior dor" if area == dor_area else ""
        linhas_placar.append(f" {area+':':<11}{nivel}{marca}")
    placar_txt = "\n".join(linhas_placar)

    ancora = resultado.get("maior_dor", {}).get("ancora", "")
    dor_declarada = contato.get("desafio") or "(não declarada)"
    contato_linha = " / ".join(x for x in [contato.get("whatsapp"), contato.get("email")] if x)

    frase = (
        f"Vi que o ponto mais frágil hoje é {dor_area} e que você citou "
        f"\"{dor_declarada}\". É por aí que a gente costuma gerar resultado mais rápido..."
    )

    return f"""NOVO DIAGNÓSTICO — {contato.get('empresa')} · {_rot(contato.get('setor'))} · {_rot(contato.get('faturamento'))}
Contato: {contato.get('nome')}, {contato.get('cargo') or '—'} — {contato_linha}
ERP atual: {_rot(contato.get('erp'))}
Urgência: {_rot(contato.get('urgencia'))}

PLACAR
{placar_txt}

PLANILHA ENVIADA? {"Sim" if tem_planilha else "Não"}

DOR DECLARADA: "{dor_declarada}"

POR ONDE COMEÇAR A CONVERSA (sugestão):
 "{frase}"

SOLUÇÃO ÂNCORA SUGERIDA: {ancora}"""


# ───────────────────────── Envios ─────────────────────────

def enviar_equipe(contato: dict, resultado: dict, relatorio: str, tem_planilha: bool = False) -> dict:
    """1 e-mail (pré-brief + relatório) + 1 WhatsApp (pré-brief) para a equipe JOGA."""
    texto = montar_texto(contato, resultado, tem_planilha)

    if not config.ENVIO_ATIVO:
        logger.info("[ENVIO_ATIVO=false] E-mail/zap da equipe NÃO enviados (dev). Pré-brief:\n%s", texto)
        return {"sucesso": True, "erro": None, "simulado": True}

    erros = []
    zap = texto + "\n\n📄 Relatório completo no e-mail.\n\n⏰ *ENTRAR EM CONTATO EM ATÉ 48 HORAS*"
    wpp = _enviar_whatsapp_sync(config.JOAO_WHATSAPP, zap)
    if not wpp["sucesso"]:
        erros.append(f"whatsapp: {wpp['erro']}")

    assunto = f"[Diagnóstico] {contato.get('empresa')} — {resultado.get('maior_dor', {}).get('area', '')}"
    mail = email_service.enviar(config.PREBRIEF_EMAILS, assunto, _email_equipe_html(texto, relatorio))
    if not mail["sucesso"]:
        erros.append(f"email: {mail['erro']}")

    return {"sucesso": not erros, "erro": "; ".join(erros) or None}


def enviar_achados_equipe(contato: dict, achados: dict) -> dict:
    """Quando o cliente sobe a planilha (2b): manda os achados reais para a equipe JOGA."""
    if not achados or not achados.get("frases"):
        return {"sucesso": True, "erro": None}
    frases = "\n".join("• " + f for f in achados["frases"])
    texto = f"📊 {contato.get('empresa')} subiu a planilha. Achados reais:\n{frases}"

    if not config.ENVIO_ATIVO:
        logger.info("[ENVIO_ATIVO=false] Achados NÃO enviados (dev):\n%s", texto)
        return {"sucesso": True, "erro": None, "simulado": True}

    erros = []
    wpp = _enviar_whatsapp_sync(config.JOAO_WHATSAPP, texto)
    if not wpp["sucesso"]:
        erros.append(f"whatsapp: {wpp['erro']}")
    html = f'<pre style="font-family:ui-monospace,monospace;white-space:pre-wrap">{_html.escape(texto)}</pre>'
    mail = email_service.enviar(config.PREBRIEF_EMAILS, f"[Diagnóstico] {contato.get('empresa')} subiu planilha", html)
    if not mail["sucesso"]:
        erros.append(f"email: {mail['erro']}")
    return {"sucesso": not erros, "erro": "; ".join(erros) or None}


def enviar_aviso_cliente(contato: dict, resultado: dict = None) -> dict:
    """E-mail curto de 'recebido' para o cliente. Gated por AVISO_CLIENTE_ATIVO. SEM WhatsApp."""
    if not (config.ENVIO_ATIVO and config.AVISO_CLIENTE_ATIVO):
        logger.info("[aviso cliente OFF] não enviado para %s", contato.get("email"))
        return {"sucesso": True, "erro": None, "simulado": True}
    email = contato.get("email")
    if not email:
        return {"sucesso": True, "erro": None}
    return email_service.enviar([email], "Recebemos o seu Diagnóstico JOGA", _email_cliente_html(contato, resultado))


# ───────────────────────── HTML ─────────────────────────

def _email_equipe_html(pretexto: str, relatorio_md: str) -> str:
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:660px;margin:auto;color:#222">
  <div style="background:{_INK};padding:16px 20px;border-radius:12px 12px 0 0">
    <span style="color:{_AMBER};font-weight:800;letter-spacing:1px">JOGA</span>
    <span style="color:{_CREAM}"> · Novo diagnóstico</span>
  </div>
  <div style="border:1px solid #e9e9e9;border-top:none;padding:22px;border-radius:0 0 12px 12px">
    <pre style="font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;font-size:13px;background:#f6f7f9;padding:14px;border-radius:8px;margin:0">{_html.escape(pretexto)}</pre>
    <h2 style="color:{_INK};margin:26px 0 6px;font-size:18px">Relatório completo</h2>
    {_md_para_html(relatorio_md)}
    <div style="margin-top:24px;padding:14px 18px;background:#fff4e0;border:1px solid {_AMBER};border-radius:10px;text-align:center;font-weight:800;color:{_INK};letter-spacing:.3px">
      ⏰ EQUIPE JOGA — ENTRAR EM CONTATO EM ATÉ 48 HORAS
    </div>
  </div>
</div>"""


def _email_cliente_html(contato: dict, resultado: dict) -> str:
    nome = (contato.get("nome") or "").split(" ")[0]
    placar = (resultado or {}).get("placar", {})
    cores = {"Crítico": "#e5484d", "Atenção": _AMBER, "Bom": "#2f9e8f", "Maduro": "#2f9e44"}
    itens = "".join(
        f'<tr><td style="padding:8px 12px;color:{_INK};border-bottom:1px solid #eee">{a}</td>'
        f'<td style="padding:8px 12px;text-align:right;font-weight:700;color:{cores.get(n, "#555")};border-bottom:1px solid #eee">{n}</td></tr>'
        for a, n in placar.items()
    )
    tabela = (
        f'<table style="width:100%;border-collapse:collapse;margin:18px 0;background:#f6f7f9;border-radius:10px;overflow:hidden">{itens}</table>'
        if itens else ""
    )
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#222">
  <div style="background:{_INK};padding:24px;border-radius:14px 14px 0 0;text-align:center">
    <div style="color:{_AMBER};font-size:24px;font-weight:800;letter-spacing:1.5px">JOGA</div>
    <div style="color:{_CREAM};font-size:12px;margin-top:3px">Soluções Empresariais</div>
  </div>
  <div style="border:1px solid #eee;border-top:none;padding:28px;border-radius:0 0 14px 14px">
    <h1 style="font-size:20px;color:{_INK};margin:0 0 12px">Recebemos o seu diagnóstico{', ' + nome if nome else ''}! ✅</h1>
    <p style="line-height:1.6;margin:0 0 8px">Obrigado por responder. Nossa equipe já está analisando as suas respostas e o seu raio-x de maturidade por área:</p>
    {tabela}
    <p style="line-height:1.6">Em <strong>até 48 horas</strong> a gente entra em contato para conversar sobre os pontos que encontramos e mostrar como a JOGA pode ajudar a organizar a sua gestão.</p>
    <p style="line-height:1.6;margin-top:18px">Até já,<br><strong>Equipe JOGA</strong></p>
  </div>
  <p style="text-align:center;color:#9aa;font-size:12px;margin-top:14px">Jogue o jogo certo com o nosso diagnóstico.</p>
</div>"""


def _md_para_html(md: str) -> str:
    """Conversão leve de markdown → HTML (títulos, negrito, listas, quebras)."""
    linhas = []
    for linha in (md or "").split("\n"):
        seguro = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _html.escape(linha))
        if linha.startswith("### "):
            linhas.append(f"<h3>{seguro[4:]}</h3>")
        elif linha.startswith("## "):
            linhas.append(f"<h2>{seguro[3:]}</h2>")
        elif linha.startswith("# "):
            linhas.append(f"<h1>{seguro[2:]}</h1>")
        elif linha.startswith("- "):
            linhas.append(f"<li>{seguro[2:]}</li>")
        elif re.match(r"^---+\s*$", linha):
            linhas.append("<hr>")
        elif linha.strip() == "":
            linhas.append("<br>")
        else:
            linhas.append(f"<p>{seguro}</p>")
    return f'<div style="font-family:Arial,Helvetica,sans-serif;line-height:1.55">{"".join(linhas)}</div>'


def _enviar_whatsapp_sync(telefone: str, texto: str) -> dict:
    """Roda o serviço async de WhatsApp a partir de um contexto síncrono (BackgroundTasks)."""
    import asyncio
    try:
        return asyncio.run(whatsapp_service.enviar_mensagem(telefone, texto))
    except Exception as e:  # noqa: BLE001
        return {"sucesso": False, "erro": str(e)}
