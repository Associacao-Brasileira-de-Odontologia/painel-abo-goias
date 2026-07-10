"""Camada de mensageria (WhatsApp) — ponto de entrada público.

A aplicação nunca deve importar um provedor concreto (ex.: ``ZApiProvider``)
diretamente — sempre use :func:`get_messaging_service`. Trocar de provedor
no futuro é implementar um novo :class:`~.provider.MessagingProvider` e
trocar a única linha que o instancia em :func:`get_messaging_service`,
sem alterar nenhum chamador.
"""

from __future__ import annotations

from django.conf import settings

from .base import MessagingService
from .exceptions import MessagingError
from .provider import MessagingProvider
from .responses import DisponibilidadeResult, MessagingResult
from .zapi import ZApiProvider, carregar_config_zapi

__all__ = [
    "MessagingService",
    "MessagingProvider",
    "MessagingError",
    "MessagingResult",
    "DisponibilidadeResult",
    "get_messaging_service",
    "messaging_configurado",
]


def messaging_configurado() -> bool:
    """True se há credenciais do provedor de mensageria ativo configuradas."""

    return carregar_config_zapi() is not None


def get_messaging_service() -> MessagingService:
    """Constrói o serviço de mensageria configurado para a aplicação.

    Hoje instancia :class:`ZApiProvider`; um novo provedor entra trocando
    apenas esta linha. Levanta ``MessagingConfigurationError`` se as
    credenciais não estiverem presentes — o chamador deve checar
    :func:`messaging_configurado` antes, no mesmo padrão já usado pelas
    demais integrações do projeto (Eduq, Dental Office, carimbo de tempo).
    """

    return MessagingService(
        ZApiProvider(),
        tentativas=settings.ZAPI_MAX_RETRIES,
        backoff_base_segundos=settings.ZAPI_RETRY_BACKOFF_SECONDS,
    )
