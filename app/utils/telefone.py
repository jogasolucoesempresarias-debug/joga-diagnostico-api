"""
Normalização de telefones brasileiros — copiado de DanfeZap (utils/telefone.py).

Formato canônico: SEM o "9 extra" de celular (JID legado da UazAPI, 12 dígitos).
    "(28) 99992-0221"  -> "552899920221"
    "5528999920221"    -> "552899920221"
"""


def normalizar_telefone_br(telefone: str) -> str:
    numero = ''.join(filter(str.isdigit, telefone or ""))

    if not numero.startswith('55'):
        numero = '55' + numero

    # Remove o "9 extra" de celular: 55 + DDD(2) + 9 + 8 dígitos → 55 + DDD(2) + 8 dígitos
    if len(numero) == 13 and numero[4] == '9':
        numero = numero[:4] + numero[5:]

    return numero
