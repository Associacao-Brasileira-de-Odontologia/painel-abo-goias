"""Tarefas assíncronas da app de Gestão de CME.

Executadas por um worker Celery separado (não pelo processo web). Veja
abo_goias/celery.py para o bootstrap do app e o .env.example para as
variáveis necessárias em produção (CELERY_BROKER_URL/REDIS_URL).
"""

from __future__ import annotations

import logging

from celery import shared_task

from .integrations.eduq import EduqAPIError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(EduqAPIError,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
)
def sincronizar_eduq_task(self) -> dict[str, int]:
    """Atualiza turmas e alunos a partir do Eduq, em segundo plano.

    Agendada via Celery Beat (ver CELERY_BEAT_SCHEDULE em settings.py). É o que
    mantém a base de alunos completa: o Eduq não oferece busca de aluno por
    nome (só ``listar_alunos`` por turma), então as telas do CME pesquisam
    apenas o que já está no banco — sem esta rotina, um aluno recém-matriculado
    só apareceria se alguém apertasse "Atualizar lista de alunos" na mão.

    Tem retry com backoff porque a janela é diária: sem ele, uma falha pontual
    de rede deixaria a base parada por 24h. Uma falha definitiva é registrada no
    log e coberta pela execução seguinte.
    """

    from .services.eduq_sync import sincronizar_eduq

    resultado = sincronizar_eduq(sincronizar_turmas=True, sincronizar_alunos=True)

    resumo = {
        "turmas_criadas": resultado.turmas.criados,
        "turmas_atualizadas": resultado.turmas.atualizados,
        "alunos_criados": resultado.alunos.criados,
        "alunos_atualizados": resultado.alunos.atualizados,
        "erros": len(resultado.turmas.erros) + len(resultado.alunos.erros),
    }

    logger.info(
        "sincronizar_eduq_task: turmas %d nova(s)/%d atualizada(s); "
        "alunos %d novo(s)/%d atualizado(s); %d erro(s)",
        resumo["turmas_criadas"],
        resumo["turmas_atualizadas"],
        resumo["alunos_criados"],
        resumo["alunos_atualizados"],
        resumo["erros"],
    )
    return resumo


@shared_task
def marcar_emprestimos_atrasados_task() -> int:
    """Marca como ATRASADO todo empréstimo com prazo vencido, em segundo plano.

    Agendada via Celery Beat (ver CELERY_BEAT_SCHEDULE em settings.py). A
    listagem de empréstimos já roda a mesma regra a cada acesso (ver
    views.emprestimos), então esta tarefa cobre o caso de ninguém visitar a
    tela — por exemplo, para o status já vir correto num alerta futuro no
    portal, sem depender de alguém abrir a listagem primeiro.
    """

    from .services.emprestimos import marcar_emprestimos_atrasados

    total = marcar_emprestimos_atrasados()
    if total:
        logger.info(
            "marcar_emprestimos_atrasados_task: %d empréstimo(s) marcado(s) "
            "como atrasado(s)",
            total,
        )
    return total
