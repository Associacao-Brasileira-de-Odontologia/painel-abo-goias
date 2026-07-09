"""Serviço de mensageria — fachada única que a aplicação usa para enviar
mensagens de WhatsApp, independente de qual provedor está por trás.

::

    MessagingProvider (Interface)
            ▲
            │
        ZApiProvider
            │
      MessagingService   ← esta classe
            │
      Aplicação Django

Nenhuma view, model ou template deve importar um provedor concreto — toda
comunicação passa por :class:`MessagingService`, obtido via
``gestao_contratos.services.messaging.get_messaging_service()``.
"""

from __future__ import annotations

import logging
from typing import Callable

from .exceptions import MessagingError
from .provider import MessagingProvider
from .responses import DisponibilidadeResult, MessagingResult
from .utils import com_retry

logger = logging.getLogger("gestao_contratos.messaging")


class MessagingService:
    """Orquestra um :class:`MessagingProvider`, padronizando retry, tratamento
    de erro e resposta. É esta classe — nunca o provedor — que a aplicação usa.

    Nenhum dos métodos de envio levanta exceção: falhas (mesmo após as
    tentativas de retry) voltam como ``MessagingResult`` com ``sucesso=False``,
    para que o chamador trate o erro como um valor de retorno, não como
    controle de fluxo por exceção.
    """

    def __init__(
        self,
        provider: MessagingProvider,
        *,
        tentativas: int = 3,
        backoff_base_segundos: float = 1.5,
    ) -> None:
        self._provider = provider
        self._tentativas = tentativas
        self._backoff_base_segundos = backoff_base_segundos

    def enviar_texto(self, destinatario: str, mensagem: str) -> MessagingResult:
        """Envia uma mensagem de texto simples."""

        return self._executar(lambda: self._provider.enviar_texto(destinatario, mensagem))

    def enviar_documento(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        legenda: str = "",
    ) -> MessagingResult:
        """Envia um arquivo como documento (ex.: PDF), com legenda opcional."""

        return self._executar(
            lambda: self._provider.enviar_documento(
                destinatario, arquivo_bytes, nome_arquivo, legenda
            )
        )

    def enviar_imagem(
        self, destinatario: str, arquivo_bytes: bytes, legenda: str = ""
    ) -> MessagingResult:
        """Envia uma imagem, com legenda opcional."""

        return self._executar(
            lambda: self._provider.enviar_imagem(destinatario, arquivo_bytes, legenda)
        )

    def enviar_arquivo(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        content_type: str,
        legenda: str = "",
    ) -> MessagingResult:
        """Envia um arquivo genérico, escolhendo o tipo de mensagem conforme
        ``content_type``."""

        return self._executar(
            lambda: self._provider.enviar_arquivo(
                destinatario, arquivo_bytes, nome_arquivo, content_type, legenda
            )
        )

    def verificar_disponibilidade(self) -> DisponibilidadeResult:
        """Verifica se o provedor está pronto para enviar mensagens agora."""

        try:
            return self._provider.verificar_disponibilidade()
        except MessagingError as exc:
            return DisponibilidadeResult(disponivel=False, detalhe=str(exc))

    def _executar(self, chamada: Callable[[], MessagingResult]) -> MessagingResult:
        try:
            return com_retry(
                chamada,
                tentativas=self._tentativas,
                backoff_base_segundos=self._backoff_base_segundos,
            )
        except MessagingError as exc:
            logger.error("messaging.falha resultado=%s", exc)
            return MessagingResult.falha(str(exc))
