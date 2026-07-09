"""Hierarquia de exceções da camada de mensageria.

Toda falha de um provedor concreto (ex.: Z-API) é convertida para uma
destas exceções antes de "subir" para a aplicação — o restante do projeto
nunca precisa conhecer o formato de erro específico de um provedor.
"""

from __future__ import annotations


class MessagingError(Exception):
    """Erro base de qualquer falha na camada de mensageria."""


class MessagingConfigurationError(MessagingError):
    """Credenciais ou parâmetros obrigatórios ausentes/inválidos."""


class MessagingAuthenticationError(MessagingError):
    """Token/instância inválidos ou sem permissão (falha de autenticação)."""


class InstanceDisconnectedError(MessagingError):
    """A instância existe mas não está conectada a uma sessão de WhatsApp."""


class QRCodePendingError(InstanceDisconnectedError):
    """A instância aguarda a leitura do QR Code para conectar."""


class InvalidRecipientError(MessagingError):
    """Número de destinatário ausente, mal formatado ou inválido."""


class MessageRejectedError(MessagingError):
    """A mensagem foi recusada pelo provedor (conteúdo, política, etc.)."""


class RateLimitExceededError(MessagingError):
    """Limite de requisições do provedor foi excedido."""


class MessagingTimeoutError(MessagingError):
    """Timeout de rede ao comunicar com o provedor."""


class ProviderUnavailableError(MessagingError):
    """Falha temporária/interna do provedor (HTTP 5xx, indisponibilidade)."""


TRANSIENT_ERRORS: tuple[type[MessagingError], ...] = (
    MessagingTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
"""Erros considerados transitórios — elegíveis para retry automático.

Erros de configuração, autenticação, destinatário inválido ou mensagem
rejeitada ficam de fora: reenviar não resolveria esses casos e arriscaria
duplicar a mensagem no destinatário quando o problema é outro.
"""
