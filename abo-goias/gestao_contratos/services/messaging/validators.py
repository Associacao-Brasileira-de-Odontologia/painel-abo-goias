"""Validação de destinatários antes do envio.

A normalização de números de celular brasileiros (adicionar DDI, remover
formatação) é responsabilidade do domínio da aplicação — ver
``gestao_contratos.services.envio.normalizar_celular``. Esta validação
garante apenas que o valor já normalizado é aceitável para envio por
qualquer provedor de WhatsApp.
"""

from __future__ import annotations

import re

from .exceptions import InvalidRecipientError

_NUMERO_VALIDO = re.compile(r"^\d{10,15}$")


def validar_destinatario(numero: str) -> str:
    """Garante que ``numero`` é um destinatário utilizável; retorna-o validado.

    Levanta ``InvalidRecipientError`` quando vazio ou fora do formato
    esperado (somente dígitos, DDI+DDD+número, de 10 a 15 dígitos).
    """

    numero = (numero or "").strip()
    if not numero or not _NUMERO_VALIDO.match(numero):
        raise InvalidRecipientError(f"Destinatário inválido: {numero!r}")
    return numero
