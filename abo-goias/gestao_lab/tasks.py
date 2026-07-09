"""Tarefas assíncronas da app de gestão de laboratório.

Executadas por um worker Celery separado (não pelo processo web). Veja
abo_goias/celery.py para o bootstrap do app e o .env.example para as
variáveis necessárias em produção (CELERY_BROKER_URL/REDIS_URL).
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def cobrar_pedidos_atrasados_task() -> int:
    """Envia cobrança por WhatsApp aos laboratórios com pedidos atrasados.

    Agendada via Celery Beat (ver CELERY_BEAT_SCHEDULE em settings.py),
    uma vez por dia. Sem credenciais da Z-API configuradas, não faz nada —
    mesmo padrão das demais integrações opcionais do projeto. Não usa
    retry automático: uma falha pontual de rede é coberta pela própria
    execução do dia seguinte, e um pedido não notificado com sucesso
    continua elegível na próxima execução (ver services/cobranca.py).
    """

    from .services.cobranca import cobrar_laboratorios_atrasados

    total = cobrar_laboratorios_atrasados()
    if total:
        logger.info(
            "cobrar_pedidos_atrasados_task: %d laboratório(s) notificado(s)", total
        )
    return total
