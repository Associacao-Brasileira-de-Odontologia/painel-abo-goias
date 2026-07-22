"""Tarefas assíncronas da app de gestão de laboratório.

Executadas por um worker Celery separado (não pelo processo web). Veja
abo_goias/celery.py para o bootstrap do app e o .env.example para as
variáveis necessárias em produção (CELERY_BROKER_URL/REDIS_URL).
"""

from __future__ import annotations

import logging

from celery import shared_task

from gestao_cme.integrations.eduq import EduqAPIError

from .integrations.dental import DentalAPIError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(DentalAPIError,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
)
def sincronizar_dental_task(self) -> dict[str, int] | None:
    """Atualiza pacientes a partir do Dental Office, em segundo plano.

    Agendada via Celery Beat. Mantém a listagem de pacientes em dia sem
    ninguém precisar apertar "Atualizar lista" — a busca dos formulários já
    consulta a API ao vivo (ver ``buscar_pacientes``), então esta rotina serve
    às telas de consulta e ao trabalho offline sobre a base local. Só
    pacientes — alunos são sincronizados do Eduq por
    ``sincronizar_eduq_lab_task``, num fluxo independente.

    Reaproveita ``executar_sync_e_registrar``, que grava o resultado em
    ``RegistroSync`` — o mesmo histórico exibido na interface, agora também
    alimentado pelas execuções automáticas.

    Substitui o cron externo apontando para ``/laboratorio/sincronizar-agendado/``:
    se aquele endpoint continuar sendo chamado por um agendador de fora, a base
    sincroniza duas vezes (sem estragar nada, mas sem necessidade).
    """

    from django.conf import settings

    from .models import RegistroSync
    from .services.dental_sync import executar_sync_e_registrar

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    if not clinic_id:
        logger.warning("sincronizar_dental_task: DENTAL_CLINIC_ID nao configurado")
        return None

    registro = executar_sync_e_registrar(
        clinic_id=clinic_id,
        disparado_por="agendamento",
        tipo=RegistroSync.Tipo.AGENDADA,
    )

    resumo = {
        "pacientes_criados": registro.pacientes_criados,
        "pacientes_atualizados": registro.pacientes_atualizados,
    }
    logger.info("sincronizar_dental_task: %s", resumo)
    return resumo


@shared_task(
    bind=True,
    autoretry_for=(EduqAPIError,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
)
def sincronizar_eduq_lab_task(self) -> dict[str, int] | None:
    """Atualiza turmas e alunos a partir do Eduq, em segundo plano.

    Agendada via Celery Beat — mesmo papel de
    ``gestao_cme.tasks.sincronizar_eduq_task``, mas numa base própria do
    laboratório (``TurmaLab``/``AlunoLab``, não compartilhada com o CME).
    Reaproveita ``executar_sync_alunos_e_registrar``, que grava o resultado em
    ``RegistroSync`` (mesmo histórico exibido na interface).
    """

    from .models import RegistroSync
    from .services.eduq_lab_sync import executar_sync_alunos_e_registrar

    registro = executar_sync_alunos_e_registrar(
        disparado_por="agendamento",
        tipo=RegistroSync.Tipo.AGENDADA,
    )

    resumo = {
        "alunos_criados": registro.alunos_criados,
        "alunos_atualizados": registro.alunos_atualizados,
    }
    logger.info("sincronizar_eduq_lab_task: %s", resumo)
    return resumo


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
