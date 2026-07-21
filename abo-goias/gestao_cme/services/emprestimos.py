"""Regras de atraso automático de empréstimos.

Roda tanto sob demanda (a cada carregamento da listagem de empréstimos, para
que o status já apareça correto mesmo se a tarefa periódica ainda não rodou)
quanto em segundo plano (ver gestao_cme/tasks.py e CELERY_BEAT_SCHEDULE em
settings.py).
"""

from __future__ import annotations

from django.utils import timezone

from ..models import Emprestimo


def marcar_emprestimos_atrasados() -> int:
    """Muda para ATRASADO todo empréstimo EMPRESTADO com prazo vencido.

    Decisão de negócio: o atraso passa a ser automático (antes, dependia de
    alguém clicar em "Marcar como atrasado"). Só considera empréstimos com
    ``data_prevista_devolucao`` preenchida — sem prazo definido não há como
    saber se está atrasado. Retorna quantos empréstimos mudaram de status,
    usado no log da tarefa periódica.
    """

    hoje = timezone.localdate()
    return Emprestimo.objects.filter(
        status=Emprestimo.Status.EMPRESTADO,
        data_prevista_devolucao__lt=hoje,
    ).update(status=Emprestimo.Status.ATRASADO)
