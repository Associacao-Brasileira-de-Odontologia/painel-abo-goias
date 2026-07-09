"""Normalização e validação de destinatários antes do envio.

Compartilhado por qualquer app que precise enviar WhatsApp — hoje
``gestao_contratos`` (link wa.me e envio automático do contrato) e
``gestao_lab`` (cobrança de material em atraso).
"""

from __future__ import annotations

import re

from .exceptions import InvalidRecipientError

_NUMERO_VALIDO = re.compile(r"^\d{10,15}$")


def normalizar_celular(celular: str) -> str:
    """Normaliza um celular para dígitos com DDI 55 (padrão E.164 sem '+').

    Remove não-dígitos e adiciona o 55 se ausente. Retorna string vazia se
    não houver nenhum dígito.
    """

    digitos = re.sub(r"\D", "", celular or "")
    if not digitos:
        return ""
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def validar_destinatario(numero: str) -> str:
    """Garante que ``numero`` é um destinatário utilizável; retorna-o validado.

    Levanta ``InvalidRecipientError`` quando vazio ou fora do formato
    esperado (somente dígitos, DDI+DDD+número, de 10 a 15 dígitos).
    """

    numero = (numero or "").strip()
    if not numero or not _NUMERO_VALIDO.match(numero):
        raise InvalidRecipientError(f"Destinatário inválido: {numero!r}")
    return numero
