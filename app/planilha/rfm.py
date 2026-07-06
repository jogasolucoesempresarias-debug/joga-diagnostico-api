"""Lógica RFM da carteira — funções puras (sem I/O).

VENDORADO de `JOGA Portfolio/comercial/rfm.py` (cópia fiel). Fonte da verdade das
regras de recência/frequência/segmentação. Não editar aqui a lógica: se mudar lá,
re-sincronizar. `analise.py` monta o snapshot a partir da planilha e chama estas funções.

Glossário:
- R (Recência): dias desde a última compra. Menor = melhor → quintil 5.
- F (Frequência): compras nos últimos 12m. Maior = melhor → quintil 5.
- M (Monetário): lucro nos últimos 12m (no diagnóstico grátis usamos faturamento).
- Régua FIXA: thresholds absolutos (10/30/45 dias).
- Régua PERSONALIZADA: dias_sem_comprar / ciclo_pessoal.
"""
import statistics
from datetime import date

REGUA_FIXA = {'ok': 10, 'normal': 30, 'atencao': 45}  # > 45 = URGENTE
CICLO_PESSOAL_FLOOR_DIAS = 7

SEGMENTOS_ORDEM = [
    'champions', 'loyal', 'cant_lose', 'at_risk',
    'new', 'potential_loyalist', 'lost', 'hibernating',
]

STATUS_ORDEM = ['ok', 'normal', 'atencao', 'urgente']


def ciclo_pessoal(datas):
    """Mediana de intervalos entre compras consecutivas. Floor 7.
    Aceita lista de strings ISO (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS) ou date objects.
    Retorna None se < 2 datas distintas."""
    if not datas or len(datas) < 2:
        return None
    parsed = []
    for d in datas:
        if isinstance(d, date):
            parsed.append(d)
        else:
            parsed.append(date.fromisoformat(str(d)[:10]))
    parsed.sort()
    intervalos = [(parsed[i + 1] - parsed[i]).days for i in range(len(parsed) - 1)]
    intervalos = [i for i in intervalos if i > 0]
    if not intervalos:
        return None
    return max(CICLO_PESSOAL_FLOOR_DIAS, int(statistics.median(intervalos)))


def status_regua_fixa(dias_sem_comprar):
    if dias_sem_comprar is None or dias_sem_comprar < 0:
        return 'urgente'
    if dias_sem_comprar <= REGUA_FIXA['ok']:
        return 'ok'
    if dias_sem_comprar <= REGUA_FIXA['normal']:
        return 'normal'
    if dias_sem_comprar <= REGUA_FIXA['atencao']:
        return 'atencao'
    return 'urgente'


def status_regua_personalizada(dias_sem_comprar, ciclo):
    if ciclo is None or ciclo <= 0:
        return status_regua_fixa(dias_sem_comprar)
    if dias_sem_comprar is None or dias_sem_comprar < 0:
        return 'urgente'
    razao = dias_sem_comprar / ciclo
    if razao < 1.0:
        return 'ok'
    if razao < 2.0:
        return 'normal'
    if razao < 3.0:
        return 'atencao'
    return 'urgente'


def lucro_perdido_projetado(lucro_12m, dias_sem_comprar, ciclo):
    if lucro_12m is None or lucro_12m <= 0 or ciclo is None or dias_sem_comprar is None:
        return 0.0
    if dias_sem_comprar < ciclo:
        return 0.0
    meses_atrasado = (dias_sem_comprar - ciclo) / 30
    return (lucro_12m / 12) * max(0.0, meses_atrasado)


def receita_perdida_projetada(venda_12m, dias_sem_comprar, ciclo):
    if venda_12m is None or venda_12m <= 0 or ciclo is None or dias_sem_comprar is None:
        return 0.0
    if dias_sem_comprar < ciclo:
        return 0.0
    meses_atrasado = (dias_sem_comprar - ciclo) / 30
    return (venda_12m / 12) * max(0.0, meses_atrasado)


def quintis(valores):
    vals = sorted(v for v in valores if v is not None)
    if not vals:
        return [0, 0, 0, 0]
    n = len(vals)
    return [vals[max(0, min(n - 1, n * q // 5 - 1))] for q in (1, 2, 3, 4)]


def quintil_de(valor, cutoffs, invertido=False):
    if valor is None:
        return 1
    q = 1
    for c in cutoffs:
        if valor > c:
            q += 1
    if invertido:
        q = 6 - q
    return max(1, min(5, q))


def segmento_canonico(r, f, m):
    if r == 5 and f == 5 and m == 5:
        return 'champions'
    if r >= 4 and f >= 4 and m >= 3:
        return 'loyal'
    if 2 <= r <= 3 and f >= 4 and m >= 4:
        return 'cant_lose'
    if 2 <= r <= 3 and f >= 3 and m >= 3:
        return 'at_risk'
    if r == 5 and f == 1:
        return 'new'
    if r >= 4 and 1 <= f <= 3:
        return 'potential_loyalist'
    if r <= 2 and f <= 2 and m <= 2:
        return 'lost'
    return 'hibernating'


def calcular_clientes(snapshot, datas_por_cliente, meta_por_cliente):
    """Entrada-saída completa de RFM. Pura.

    snapshot: lista de dicts {CODCLI, DiasSemComprar, Compras12m, Lucro12m, Venda12m, UltimaCompra}
    datas_por_cliente: {codcli: [datas_iso]}
    meta_por_cliente: {codcli: {cliente, cidade, uf, telefone, codusur1, bloqueio}}
    """
    cuts_r = quintis(c.get('DiasSemComprar') for c in snapshot)
    ativos = [c for c in snapshot if (c.get('Compras12m') or 0) >= 1]
    cuts_f = quintis(c.get('Compras12m') for c in ativos)
    cuts_m = quintis(c.get('Lucro12m') for c in ativos)

    resultado = []
    for c in snapshot:
        codcli = c.get('CODCLI')
        dias = c.get('DiasSemComprar') or 0
        compras = c.get('Compras12m') or 0
        lucro = c.get('Lucro12m') or 0.0
        venda = c.get('Venda12m') or 0.0

        ciclo = ciclo_pessoal(datas_por_cliente.get(codcli, []))
        r = quintil_de(dias, cuts_r, invertido=True)
        if compras >= 1:
            f = quintil_de(compras, cuts_f)
            m = quintil_de(lucro, cuts_m)
        else:
            f, m = 1, 1
        seg = segmento_canonico(r, f, m)
        s_fixa = status_regua_fixa(dias)
        s_pers = status_regua_personalizada(dias, ciclo)
        lp = lucro_perdido_projetado(lucro, dias, ciclo)
        rp = receita_perdida_projetada(venda, dias, ciclo)

        meta = meta_por_cliente.get(codcli, {})
        resultado.append({
            'codcli':                codcli,
            'cliente':               meta.get('cliente') or f'Cliente #{codcli}',
            'cidade':                meta.get('cidade'),
            'uf':                    meta.get('uf'),
            'codusur':               meta.get('codusur1'),
            'telefone':              meta.get('telefone'),
            'bloqueio':              meta.get('bloqueio'),
            'recencia_dias':         dias,
            'frequencia_12m':        compras,
            'lucro_12m':             lucro,
            'venda_12m':             venda,
            'ciclo_pessoal':         ciclo,
            'lucro_perdido_proj':    round(lp, 2),
            'receita_perdida_proj':  round(rp, 2),
            'status_fixa':           s_fixa,
            'status_personalizada':  s_pers,
            'segmento':              seg,
            'r':                     r,
            'f':                     f,
            'm':                     m,
            'ultima_compra':         str(c.get('UltimaCompra', ''))[:10] or None,
        })
    return resultado


def agregar_distribuicoes(clientes, modo='personalizada'):
    regua = {s: 0 for s in STATUS_ORDEM}
    segmentos = {s: 0 for s in SEGMENTOS_ORDEM}
    status_key = 'status_personalizada' if modo == 'personalizada' else 'status_fixa'
    for c in clientes:
        regua[c[status_key]] = regua.get(c[status_key], 0) + 1
        segmentos[c['segmento']] = segmentos.get(c['segmento'], 0) + 1
    total = len(clientes)
    ok_normal = regua['ok'] + regua['normal']
    return {
        'regua':     {**regua, 'pct_ok_normal': (ok_normal / total) if total else 0},
        'segmentos': segmentos,
        'total_clientes': total,
    }


def histograma_recencia(clientes, bins=None):
    """Distribuição de dias-sem-comprar. Default: 0-7, 8-15, 16-30, 31-60, 61-90, 91-180, 181+."""
    if bins is None:
        bins = [(0, 7), (8, 15), (16, 30), (31, 60), (61, 90), (91, 180), (181, 9999)]
    out = [{'bin': f'{lo}-{hi}' if hi < 9999 else f'{lo}+', 'count': 0} for lo, hi in bins]
    for c in clientes:
        d = c['recencia_dias']
        for i, (lo, hi) in enumerate(bins):
            if lo <= d <= hi:
                out[i]['count'] += 1
                break
    return out
