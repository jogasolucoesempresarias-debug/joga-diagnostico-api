# Diagnóstico JOGA — API (FastAPI)

Backend do **Diagnóstico JOGA** — a porta de entrada comercial da JOGA. Recebe as respostas do
questionário do site, calcula um **placar de maturidade** (sem cifras), gera um **relatório
personalizado por IA**, dispara um **pré-brief pra equipe** (WhatsApp + e-mail) e manda um
**e-mail de "recebido" pro cliente**. Opcionalmente, o lead sobe uma planilha e a IA analisa a
carteira de verdade (Fase 2b).

## Estado
- **Fase 2a** (miolo): questionário → placar → relatório IA → pré-brief. ✅
- **Fase 2b** (planilha): upload do export cru → IA mapeia colunas → análise RFM → achados. ✅ (motor
  pronto; a **UI de upload fica OFF em produção** via flag `NEXT_PUBLIC_UPLOAD_ATIVO` no `sitejoga`).
- **Admin**, **e-mail pro cliente** e **5º pilar Financeiro** incluídos.

## Rodar local

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
copy .env.example .env             # preencha OPENAI_API_KEY; deixe ENVIO_ATIVO=false em dev
uvicorn app.main:app --reload
```

- Health: `GET http://localhost:8000/api/diagnostico/health` → `{"status":"ok"}`
- Precisa de um Postgres em `DATABASE_URL` (dev: local; prod: `postgres_postgres/joga_diagnostico`).
  Sem banco, `/health` e o `pytest` funcionam; o `/submit` real exige o Postgres. O `init_db` cria as
  tabelas no boot **com retry** (sobrevive ao banco ficar pronto depois do backend subir).

## Testes

```bash
pytest            # scoring + submit + análise de planilha (banco e IA mockados; nenhuma rede)
```

## Endpoints

| Método | Rota | O quê |
|---|---|---|
| GET | `/api/diagnostico/health` | healthcheck |
| POST | `/api/diagnostico/submit` | recebe o questionário; devolve placar parcial + oportunidades |
| POST | `/api/diagnostico/upload` | (2b) sobe planilha; devolve achados ou pede confirmação de colunas |
| GET | `/api/diagnostico/modelo` | (2b) baixa a planilha-modelo |
| GET | `/api/diagnostico/admin` (e `/admin`) | painel de leads (login por token) |

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
  "faturamento": "500k_1mi",
  "colaboradores": "51_100",
  "desafio": "Perdemos clientes e só percebo tarde demais",
  "urgencia": "3_meses",
  "respostas": {
    "q5": "planilhas", "q6": "mes", "q7": "dia_inteiro",
    "q8": "faturamento", "q9": "fim_mes", "q10": "esforco",
    "q19": "lucro_faturamento", "q20": "inad_nao", "q21": "dre_nunca",
    "q11": "nocao", "q12": "informal", "q13": "nao_sei",
    "q14": "estimo", "q15": "as_vezes", "q16": "misto"
  }
}
```

Resposta (parcial, na hora):

```json
{
  "id": 1,
  "placar": {
    "Dados": "Atenção", "Comercial": "Crítico", "Financeiro": "Crítico",
    "Gestão de Clientes": "Atenção", "Estoque": "Crítico"
  },
  "oportunidades": ["Financeiro no escuro: ...", "Comercial no escuro: ...", "Estoque no feeling: ..."],
  "mensagem": "Recebemos seu diagnóstico. A JOGA entra em contato em até 48h."
}
```

## Áreas e códigos

**5 áreas no placar:** **Dados · Comercial · Financeiro · Gestão de Clientes · Estoque**
(Serviços não pontua Estoque). Níveis: **Crítico · Atenção · Bom · Maduro**.

Cada pergunta manda um **código** (não o texto). Tabela completa dos códigos q1–q21 em
[app/schemas.py](app/schemas.py); regras de pontuação em [app/scoring.py](app/scoring.py).
Bloco Financeiro: `q19` lucro líquido · `q20` inadimplência (com opção "não vendo a prazo") · `q21` DRE/caixa.

## Envio (WhatsApp/e-mail)

Duas flags:
- **`ENVIO_ATIVO`** (mestra): `false` = só loga; `true` = dispara de verdade.
- **`AVISO_CLIENTE_ATIVO`**: liga o e-mail de "recebido" pro cliente (independe da UazAPI).

Quando ligado:
- **Equipe JOGA:** 1 e-mail (pré-brief + relatório) + 1 WhatsApp (pré-brief) → `PREBRIEF_EMAILS` / `JOAO_WHATSAPP`.
- **Cliente:** 1 e-mail de "recebido" (sem WhatsApp por ora — aguardando a instância UazAPI da JOGA).
- **Planilha (2b):** ao subir, a equipe recebe os achados.

Remetente Resend: `RESEND_FROM=joga@jogasolucoes.com.br` (domínio verificado). WhatsApp via UazAPI
(`UAZAPI_URL`/`UAZAPI_TOKEN`).

## Admin

`/admin` (redirect) ou `/api/diagnostico/admin` → login por **`ADMIN_TOKEN`**. Lista os leads com busca/
filtros/stats e, no detalhe, mostra placar + oportunidades + achados + relatório + pré-brief.

## Regras do produto (spec)

- **Nenhum valor em R$** no relatório (decisão do João). Só maturidade + benchmark + (2b) dado real.
- Entrega **O QUÊ + PORQUÊ**, nunca o **COMO** (o "como" é o produto pago, vendido na call).
- **LGPD:** consentimento obrigatório; a planilha (2b) é analisada **em memória e descartada** (só os
  achados ficam salvos).

Fonte da verdade do produto: `JOGA-Brand/Diagnostico_JOGA_Spec_v1.md`
(+ `JOGA-Brand/Financeiro_Pilar_Plano.md`).

## Deploy

Imagem `ghcr.io/jogasolucoesempresarias-debug/joga-diagnostico-api:latest` (GitHub Action no push `main`).
Stack Swarm/Traefik: roteia `Host(jogasolucoes.com.br) && (PathPrefix(/api) || PathPrefix(/admin))` →
porta 8000. Mesma origem do site → sem CORS. Segredos ficam no `docker-compose.prod.yml` (gitignored,
aplicado via Portainer). Banco: `CREATE DATABASE joga_diagnostico` no `postgres_postgres` (uma vez).
