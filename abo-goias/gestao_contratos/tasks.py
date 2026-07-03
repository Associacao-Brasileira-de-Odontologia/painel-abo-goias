"""Tarefas assíncronas da app de gestão de contratos.

Executadas por um worker Celery separado (não pelo processo web). Veja
abo_goias/celery.py para o bootstrap do app e o .env.example para as
variáveis necessárias em produção (CELERY_BROKER_URL/REDIS_URL).
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)
def enviar_dental_task(self, contrato_pk: int) -> None:
    """Envia o contrato assinado ao Dental Office, com retry automático.

    Disparada logo após a conclusão da assinatura (services/assinatura.py).
    Falhas de rede/API (RuntimeError) acionam retry com backoff exponencial;
    um contrato removido antes da execução apenas encerra a tarefa sem retry,
    já que reenviar não teria efeito.
    """

    from .models import ContratoGerado
    from .services.envio_dental import enviar_contrato_ao_dental

    try:
        contrato = ContratoGerado.objects.select_related("paciente").get(pk=contrato_pk)
    except ContratoGerado.DoesNotExist:
        logger.error("enviar_dental_task: contrato %s não encontrado", contrato_pk)
        return

    ok, erro = enviar_contrato_ao_dental(contrato)
    if not ok:
        raise RuntimeError(erro)


@shared_task
def expirar_sessoes_vencidas_task() -> int:
    """Limpeza periódica (Celery Beat) das sessões de assinatura vencidas.

    Rede de segurança complementar ao lazy-expire já feito sob demanda em
    services/assinatura.sessao_ativa() — garante a limpeza mesmo que
    ninguém volte a abrir a tela de pós-geração do contrato.
    """

    from .services.assinatura import expirar_sessoes_globalmente

    total = expirar_sessoes_globalmente()
    if total:
        logger.info("expirar_sessoes_vencidas_task: %d sessão(ões) expirada(s)", total)
    return total
