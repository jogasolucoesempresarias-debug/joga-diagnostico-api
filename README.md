# Diagnóstico JOGA — API (FastAPI)

Backend do **Diagnóstico JOGA** — a porta de entrada comercial da JOGA. Recebe as respostas do
questionário do site, calcula um **placar de maturidade** (sem cifras), gera um **relatório
personalizado por IA** e dispara um **pré-brief pro João** por WhatsApp + e-mail.

> **Fase 2a** (esta): questionário → placar → relatório IA → pré-brief. **Sem** upload de planilha.
> Fase 2b (futura): upload do export cru + leitura de colunas por IA + análise RFM.

## Rodar local

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
copy .env.example .env             # e preencha OPENAI_API_KEY; deixe ENVIO_ATIVO=false em dev
uvicorn app.main:app --reload
```

- Health: `GET http://localhost:8000/api/diagnostico/health` → `{"status":"ok"}`
- Precisa de um Postgres em `DATABASE_URL` (dev: local; prod: `postgres_postgres/joga_diagnostico`).
  Sem banco, o `/health` e o `pytest` funcionam; o `/submit` real exige o Postgres para salvar o lead.

## Testes

```bash
pytest            # scoring + submit (banco e IA mockados; nenhuma rede)
```

## Endpoints

| Método | Rota | O quê |
|---|---|---|
| GET | `/api/diagnostico/health` | healthcheck |
| POST | `/api/diagnostico/submit` | recebe o questionário; devolve placar parcial + oportunidades |

### Payload de exemplo (`POST /submit`)

```json
{
  "nome": "Maria Gestora",
  "empresa": "Atacado Central",
  "cargo": "Sócia",
  "whatsapp": "28999920221",
  "email": "maria@atacadocentral.com",
  "consent": true,
  "setor": "atacado",
  "erp": "winthor",
  "faturamento": "500k_2mi",
  "colaboradores": "11_50",
  "desafio": "Perdemos clientes e só percebo tarde demais",
  "urgencia": "3_meses",
  "respostas": {
    "q5": "planilhas", "q6": "mes", "q7": "dia_inteiro",
    "q8": "faturamento", "q9": "fim_mes", "q10": "esforco",
    "q11": "nocao", "q12": "informal", "q13": "nao_sei",
    "q14": "estimo", "q15": "as_vezes", "q16": "misto"
  }
}
```

Resposta (parcial, na hora):

```json
{
  "id": 1,
  "placar": {"Dados": "Atenção", "Comercial": "Atenção", "Carteira": "Atenção", "Estoque": "Atenção"},
  "oportunidades": ["Carteira sem gestão: ...", "Comercial no escuro: ...", "Decisão sem dados: ..."],
  "mensagem": "Recebemos seu diagnóstico. A JOGA entra em contato em até 48h."
}
```

## Códigos das respostas

Cada pergunta manda um **código** (não o texto). Tabela completa em [app/schemas.py](app/schemas.py).
Áreas do placar: **Dados · Comercial · Carteira · Estoque** (Serviços não pontua Estoque).
Níveis: **Crítico · Atenção · Bom · Maduro**. Regras em [app/scoring.py](app/scoring.py).

## Envio (WhatsApp/e-mail)

Controlado por `ENVIO_ATIVO`:
- `false` (dev): **não dispara** nada, só loga o que enviaria.
- `true`: dispara pré-brief (WhatsApp UazAPI + Resend p/ `PREBRIEF_EMAILS`) e o relatório pro lead.

Remetente Resend: `RESEND_FROM=joga@jogasolucoes.com.br` (domínio já verificado na conta da JOGA).

## Regras do produto (spec)

- **Nenhum valor em R$** no relatório (decisão do João). Só maturidade + benchmark + (2b) dado real.
- Entrega **O QUÊ + PORQUÊ**, nunca o **COMO** (o "como" é o produto pago, vendido na call).
- **LGPD:** consentimento obrigatório; na 2a não há arquivo bruto para descartar.

Fonte da verdade do produto: `JOGA-Brand/Diagnostico_JOGA_Spec_v1.md`.
