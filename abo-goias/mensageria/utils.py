"""Utilitários compartilhados da camada de mensageria: retry com backoff
exponencial e logging estruturado que nunca grava tokens/credenciais."""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from .exceptions import TRANSIENT_ERRORS, MessagingError

T = TypeVar("T")

logger = logging.getLogger("gestao_contratos.messaging")


def com_retry(
    func: Callable[[], T],
    *,
    tentativas: int,
    backoff_base_segundos: float,
) -> T:
    """Executa ``func`` com retry e backoff exponencial para erros transitórios.

    Erros que não são transitórios (configuração, autenticação, destinatário
    inválido, mensagem rejeitada) propagam imediatamente, sem retry —
    reenviar não resolveria e arriscaria duplicar a mensagem no
    destinatário. Erros transitórios (timeout, indisponibilidade, limite de
    requisições) são tentados novamente com espera crescente (1x, 2x, 4x...
    o backoff base) até esgotar ``tentativas``.
    """

    ultima_excecao: MessagingError | None = None
    for tentativa in range(1, max(tentativas, 1) + 1):
        try:
            return func()
        except TRANSIENT_ERRORS as exc:
            ultima_excecao = exc
            if tentativa >= tentativas:
                break
            espera = backoff_base_segundos * (2 ** (tentativa - 1))
            logger.warning(
                "messaging.retry tentativa=%s/%s aguardando=%.1fs motivo=%s",
                tentativa,
                tentativas,
                espera,
                exc,
            )
            time.sleep(espera)

    assert ultima_excecao is not None
    raise ultima_excecao


def log_envio(
    *,
    endpoint: str,
    destinatario: str,
    tipo_mensagem: str,
    status_http: int | None,
    duracao_segundos: float,
    sucesso: bool,
    resultado: str,
) -> None:
    """Registra uma tentativa de envio em formato estruturado.

    Nunca recebe nem registra token, instance id ou qualquer credencial —
    apenas metadados operacionais da chamada. O número do destinatário é
    mascarado, mantendo só DDI/DDD e os dois últimos dígitos.
    """

    logger.info(
        "messaging.envio endpoint=%s destinatario=%s tipo=%s status_http=%s "
        "duracao_ms=%d sucesso=%s resultado=%s",
        endpoint,
        _mascarar_destinatario(destinatario),
        tipo_mensagem,
        status_http,
        int(duracao_segundos * 1000),
        sucesso,
        resultado,
    )


def _mascarar_destinatario(numero: str) -> str:
    """Mascara os dígitos centrais de um número no log (mantém início e fim)."""

    numero = numero or ""
    if len(numero) <= 6:
        return "*" * len(numero)
    return f"{numero[:4]}{'*' * (len(numero) - 6)}{numero[-2:]}"
