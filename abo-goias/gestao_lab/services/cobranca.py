"""Cobrança automática por WhatsApp de pedidos de material em atraso.

Roda periodicamente (ver gestao_lab/tasks.py e CELERY_BEAT_SCHEDULE em
settings.py), agrega por laboratório todos os PedidoMaterial com
status ATRASADO ainda não cobrados hoje e envia uma única mensagem de
texto via mensageria (Z-API) — em vez de uma mensagem por pedido, o que
seria repetitivo para laboratórios com vários pedidos atrasados.

Cada pedido incluído numa cobrança é marcado com
cobranca_whatsapp_enviada_em; a próxima execução no mesmo dia ignora esses
pedidos, evitando notificar o laboratório repetidamente. Sem credenciais
da Z-API configuradas, a cobrança fica desativada sem erro — mesmo padrão
já usado pelo envio automático de contratos.
"""

from __future__ import annotations

import logging
from itertools import groupby

from django.db.models import Q
from django.utils import timezone
from gestao_lab.models import Laboratorio, PedidoMaterial
from mensageria import get_messaging_service, messaging_configurado
from mensageria.validators import normalizar_celular

logger = logging.getLogger(__name__)

__all__ = ["cobranca_configurada", "cobrar_laboratorios_atrasados"]


def cobranca_configurada() -> bool:
    """True se há credenciais do provedor de mensageria configuradas."""

    return messaging_configurado()


def _inicio_do_dia():
    agora = timezone.localtime()
    return agora.replace(hour=0, minute=0, second=0, microsecond=0)


def _pedidos_pendentes_de_cobranca():
    """Pedidos atrasados, com WhatsApp do laboratório e ainda não cobrados hoje."""

    return (
        PedidoMaterial.objects.filter(status=PedidoMaterial.Status.ATRASADO)
        .exclude(laboratorio__whatsapp="")
        .filter(
            Q(cobranca_whatsapp_enviada_em__isnull=True)
            | Q(cobranca_whatsapp_enviada_em__lt=_inicio_do_dia())
        )
        .select_related("laboratorio")
        .order_by("laboratorio_id", "previsao_entrega")
    )


def _montar_mensagem(laboratorio: Laboratorio, pedidos: list[PedidoMaterial]) -> str:
    hoje = timezone.localdate()
    linhas = [
        f"Olá, {laboratorio.nome}! A ABO Goiás identificou "
        f"{len(pedidos)} pedido(s) de material em atraso:",
        "",
    ]
    for pedido in pedidos:
        dias_atraso = (hoje - pedido.previsao_entrega).days
        linhas.append(
            f"• Pedido #{pedido.pk} — previsto para "
            f"{pedido.previsao_entrega:%d/%m/%Y}, {dias_atraso} dia(s) de atraso."
        )
    linhas.append("")
    linhas.append(
        "Por favor, regularize a entrega o quanto antes. Em caso de dúvidas, "
        "entre em contato com a coordenação responsável."
    )
    return "\n".join(linhas)


def cobrar_laboratorios_atrasados() -> int:
    """Envia a cobrança do dia; retorna quantos laboratórios foram notificados.

    Não faz nada (retorna 0) se a mensageria não estiver configurada. Uma
    falha de envio para um laboratório não impede a cobrança dos demais —
    o pedido problemático simplesmente permanece elegível na próxima
    execução (não é marcado com cobranca_whatsapp_enviada_em).
    """

    if not cobranca_configurada():
        return 0

    pedidos = list(_pedidos_pendentes_de_cobranca())
    total_notificados = 0

    for _laboratorio_id, grupo in groupby(pedidos, key=lambda p: p.laboratorio_id):
        pedidos_do_lab = list(grupo)
        laboratorio = pedidos_do_lab[0].laboratorio
        destinatario = normalizar_celular(laboratorio.whatsapp)
        if not destinatario:
            continue

        mensagem = _montar_mensagem(laboratorio, pedidos_do_lab)
        resultado = get_messaging_service().enviar_texto(destinatario, mensagem)

        if not resultado.sucesso:
            logger.error(
                "cobrar_laboratorios_atrasados: falha ao notificar "
                "laboratorio_id=%s: %s",
                laboratorio.pk,
                resultado.erro,
            )
            continue

        PedidoMaterial.objects.filter(
            pk__in=[pedido.pk for pedido in pedidos_do_lab]
        ).update(cobranca_whatsapp_enviada_em=timezone.now())
        total_notificados += 1

    return total_notificados
