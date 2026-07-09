"""Envio automático do contrato assinado ao paciente via WhatsApp.

Usa a camada de mensageria (``gestao_contratos.services.messaging``),
atualmente configurada para a Z-API — ver
``services/messaging/zapi.py``. Este módulo não conhece detalhes de
protocolo do provedor: só monta os dados do envio (destinatário, PDF,
legenda) e traduz o resultado em eventos/status do contrato.

Sem credenciais configuradas, ``whatsapp_configurado()`` retorna False e o
chamador (``services/assinatura.py``) simplesmente não agenda o envio
automático — o fluxo manual (link wa.me na tela de pós-geração) continua
sendo o único caminho, sem nenhuma mudança de comportamento até que as
credenciais sejam configuradas.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from ..envio import normalizar_celular
from ..messaging import get_messaging_service, messaging_configurado

if TYPE_CHECKING:
    from gestao_contratos.models import ContratoGerado

logger = logging.getLogger(__name__)

__all__ = [
    "whatsapp_configurado",
    "enviar_whatsapp_contrato",
]

_LEGENDA_CONTRATO = (
    "Olá! Seu contrato foi assinado com sucesso. Segue uma cópia em PDF. "
    "Obrigado — ABO Goiás."
)


def whatsapp_configurado() -> bool:
    """True se há credenciais do provedor de mensageria configuradas."""

    return messaging_configurado()


def enviar_whatsapp_contrato(contrato: "ContratoGerado") -> tuple[bool, str]:
    """Envia o PDF do contrato ao paciente via WhatsApp.

    Prefere o PDF assinado, igual aos demais canais de envio. Retorna
    (True, "") em sucesso ou (False, erro). Não é chamada quando
    whatsapp_configurado() é False — quem agenda a tarefa (services/
    assinatura.py) já garante essa checagem antes.
    """

    from ..assinatura import registrar_evento
    from ..documentos import obter_melhor_pdf_bytes

    paciente = contrato.paciente
    registrar_evento(contrato, "whatsapp_iniciado")

    destinatario = normalizar_celular(paciente.celular or "")
    if not destinatario:
        erro = "Paciente sem celular válido — não é possível enviar por WhatsApp."
        logger.error("enviar_whatsapp_contrato: %s (contrato_pk=%s)", erro, contrato.pk)
        _marcar_erro(contrato, erro)
        return False, erro

    arquivo_bytes = obter_melhor_pdf_bytes(contrato)
    if not arquivo_bytes:
        erro = "Contrato sem PDF disponível para envio."
        logger.error("enviar_whatsapp_contrato: %s (contrato_pk=%s)", erro, contrato.pk)
        _marcar_erro(contrato, erro)
        return False, erro

    nome_arquivo = f"contrato_{contrato.tipo}_{paciente.id_dental}.pdf"

    resultado = get_messaging_service().enviar_documento(
        destinatario=destinatario,
        arquivo_bytes=arquivo_bytes,
        nome_arquivo=nome_arquivo,
        legenda=_LEGENDA_CONTRATO,
    )
    if not resultado.sucesso:
        logger.error(
            "enviar_whatsapp_contrato: %s (contrato_pk=%s)", resultado.erro, contrato.pk
        )
        _marcar_erro(contrato, resultado.erro)
        return False, resultado.erro

    contrato.status_envio = "enviado_whatsapp"
    contrato.enviado_em = timezone.now()
    contrato.save(update_fields=["status_envio", "enviado_em", "atualizado_em"])
    registrar_evento(contrato, "whatsapp_concluido", message_id=resultado.message_id)
    return True, ""


def _marcar_erro(contrato: "ContratoGerado", erro: str) -> None:
    from ..assinatura import registrar_evento

    registrar_evento(contrato, "whatsapp_erro", erro=erro)
