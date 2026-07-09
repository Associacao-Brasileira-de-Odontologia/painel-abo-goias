"""Estruturas de resposta padronizadas da camada de mensageria.

Qualquer provedor concreto (Z-API hoje, outro amanhã) traduz sua resposta
nativa para :class:`MessagingResult`/:class:`DisponibilidadeResult` antes de
devolvê-la — a aplicação nunca lida com o formato de resposta de um
provedor específico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageStatus(str, Enum):
    """Resultado padronizado de uma tentativa de envio."""

    ENVIADA = "enviada"
    FALHA = "falha"


@dataclass(frozen=True)
class MessagingResult:
    """Resultado padronizado de qualquer operação de envio.

    ``sucesso`` é a forma preferida de checar o resultado; ``message_id``
    e ``erro`` trazem o detalhe conforme o caso.
    """

    status: MessageStatus
    message_id: str = ""
    erro: str = ""
    detalhes: dict[str, Any] = field(default_factory=dict)

    @property
    def sucesso(self) -> bool:
        return self.status is MessageStatus.ENVIADA

    @classmethod
    def ok(cls, message_id: str, **detalhes: Any) -> "MessagingResult":
        return cls(
            status=MessageStatus.ENVIADA, message_id=message_id, detalhes=detalhes
        )

    @classmethod
    def falha(cls, erro: str, **detalhes: Any) -> "MessagingResult":
        return cls(status=MessageStatus.FALHA, erro=erro, detalhes=detalhes)


@dataclass(frozen=True)
class DisponibilidadeResult:
    """Resultado da checagem de disponibilidade do serviço de mensageria."""

    disponivel: bool
    detalhe: str = ""
