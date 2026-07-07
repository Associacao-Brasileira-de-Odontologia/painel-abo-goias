"""Envio automático do contrato assinado ao paciente via WhatsApp.

Usa a Meta WhatsApp Business Cloud API quando configurada (ver
meta_cloud.py). Sem configuração, whatsapp_configurado() retorna False e
o chamador (services/assinatura.py) simplesmente não agenda o envio
automático — o fluxo manual (link wa.me na tela de pós-geração) continua
sendo o único caminho, sem nenhuma mudança de comportamento até que as
credenciais sejam configuradas.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from ..envio import normalizar_celular
from .meta_cloud import MetaWhatsAppClient, MetaWhatsAppError, carregar_config_meta

if TYPE_CHECKING:
    from gestao_contratos.models import ContratoGerado

logger = logging.getLogger(__name__)

__all__ = [
    "whatsapp_configurado",
    "enviar_whatsapp_contrato",
    "MetaWhatsAppError",
]


def whatsapp_configurado() -> bool:
    """True se há credenciais da Meta Cloud API configuradas no ambiente."""

    return carregar_config_meta() is not None


def enviar_whatsapp_contrato(contrato: "ContratoGerado") -> tuple[bool, str]:
    """Envia o PDF do contrato ao paciente via WhatsApp (Meta Cloud API).

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

    try:
        client = MetaWhatsAppClient()
        message_id = client.enviar_documento(
            destinatario=destinatario,
            arquivo_bytes=arquivo_bytes,
            nome_arquivo=nome_arquivo,
            nome_paciente=paciente.nome,
        )
    except MetaWhatsAppError as exc:
        erro = str(exc)
        logger.error("enviar_whatsapp_contrato: %s (contrato_pk=%s)", erro, contrato.pk)
        _marcar_erro(contrato, erro)
        return False, erro

    contrato.status_envio = "enviado_whatsapp"
    contrato.enviado_em = timezone.now()
    contrato.save(update_fields=["status_envio", "enviado_em", "atualizado_em"])
    registrar_evento(contrato, "whatsapp_concluido", message_id=message_id)
    return True, ""


def _marcar_erro(contrato: "ContratoGerado", erro: str) -> None:
    from ..assinatura import registrar_evento

    registrar_evento(contrato, "whatsapp_erro", erro=erro)
