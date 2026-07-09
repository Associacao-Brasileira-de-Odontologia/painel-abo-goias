"""Interface que qualquer provedor de mensageria deve implementar.

::

    MessagingProvider (Interface)
            ▲
            │
        ZApiProvider

Novos provedores (ex.: Twilio, uma futura volta à Cloud API oficial etc.)
implementam esta interface e passam a funcionar com o restante da aplicação
sem qualquer alteração em :class:`~.base.MessagingService` ou nos
chamadores — a troca fica isolada em :func:`~.get_messaging_service`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .responses import DisponibilidadeResult, MessagingResult


class MessagingProvider(ABC):
    """Contrato mínimo de um provedor de envio de mensagens de WhatsApp."""

    @abstractmethod
    def enviar_texto(self, destinatario: str, mensagem: str) -> MessagingResult:
        """Envia uma mensagem de texto simples."""

    @abstractmethod
    def enviar_documento(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        legenda: str = "",
    ) -> MessagingResult:
        """Envia um arquivo como documento (ex.: PDF), com legenda opcional."""

    @abstractmethod
    def enviar_imagem(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        legenda: str = "",
    ) -> MessagingResult:
        """Envia uma imagem, com legenda opcional."""

    @abstractmethod
    def enviar_arquivo(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        content_type: str,
        legenda: str = "",
    ) -> MessagingResult:
        """Envia um arquivo genérico, escolhendo o tipo de mensagem conforme
        ``content_type`` (imagem, documento, etc.)."""

    @abstractmethod
    def verificar_disponibilidade(self) -> DisponibilidadeResult:
        """Verifica se o provedor está pronto para enviar mensagens agora."""
