"""
Schemas Pydantic v2 do endpoint /api/diagnostico/submit.

O front (sitejoga) envia contato + `respostas` (dict de códigos). Os códigos
aceitos por pergunta estão documentados abaixo e no README — o scoring.py
usa exatamente esses códigos. Códigos desconhecidos/ausentes viram 0 ponto.

Perguntas (spec §4):
  q1 setor        : atacado | varejo | industria | logistica | servicos | outro
  q2 faturamento  : ate100k | 100k_500k | 500k_1mi | 1mi_2mi | 2mi_5mi | 5mi_10mi | mais10mi
  q3 colaborador  : 1_10 | 11_50 | 51_100 | 101_200 | mais200
  q4 erp          : winthor | sankhya | bling | outro | nenhum
  q5 indicadores  : cabeca | planilhas | erp | bi | nao_acompanho
  q6 frequencia   : dia | semana | mes | problema | nao_olho
  q7 tempo        : quase_nada | horas | dia_inteiro | mais | nao_sei
  q8 margem       : faturamento | fat_margens | margem_completa | nao_acompanho
  q9 metas        : sem_metas | fim_mes | de_perto
  q10 vendedor    : nao | esforco | facil
  q11 perdeu      : nao_ideia | nocao | exato
  q12 classifica  : nao | informal | formal
  q13 inativo     : menos10 | 10_25 | 25_50 | mais50 | nao_sei
  q14 parado      : nao | estimo | exato
  q15 ruptura     : sempre | as_vezes | raramente
  q16 compras     : feeling | misto | dados
  q17 dor         : texto livre (vai em `desafio`)
  q18 urgencia    : pra_ontem | 3_meses | pesquisando
  q19 lucro       : lucro_exato | lucro_estimo | lucro_faturamento
  q20 inadimplenc : inad_controlo | inad_nocao | inad_nao | inad_nao_prazo
  q21 dre_caixa   : dre_mes | dre_as_vezes | dre_nunca
"""
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class SubmitBody(BaseModel):
    # Muro de captura
    nome: str = Field(..., min_length=1)
    empresa: str = Field(..., min_length=1)
    cargo: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    consent: bool = False

    # Contexto (também presente nas respostas; mantido explícito p/ salvar/pré-brief)
    setor: Optional[str] = None
    erp: Optional[str] = None
    faturamento: Optional[str] = None
    colaboradores: Optional[str] = None
    desafio: Optional[str] = None       # dor declarada (q17, campo aberto)
    urgencia: Optional[str] = None      # q18

    # Respostas do questionário (códigos por pergunta)
    respostas: Dict[str, str] = Field(default_factory=dict)

    @field_validator("consent")
    @classmethod
    def _consent_obrigatorio(cls, v: bool) -> bool:
        if not v:
            raise ValueError("É necessário aceitar o consentimento (LGPD).")
        return v

    @model_validator(mode="after")
    def _pelo_menos_um_contato(self):
        if not (self.whatsapp or self.email):
            raise ValueError("Informe ao menos WhatsApp ou e-mail.")
        return self

    def contato(self) -> dict:
        """Dict de contato/contexto para salvar e montar o pré-brief."""
        return {
            "nome": self.nome,
            "empresa": self.empresa,
            "cargo": self.cargo,
            "whatsapp": self.whatsapp,
            "email": self.email,
            "setor": self.setor or self.respostas.get("q1"),
            "erp": self.erp or self.respostas.get("q4"),
            "faturamento": self.faturamento or self.respostas.get("q2"),
            "colaboradores": self.colaboradores or self.respostas.get("q3"),
            "desafio": self.desafio,
            "urgencia": self.urgencia or self.respostas.get("q18"),
        }


class RespostaParcial(BaseModel):
    """O que volta na hora para a tela (parcial, sem cifras)."""
    placar: Dict[str, str]
    oportunidades: list
    mensagem: str
