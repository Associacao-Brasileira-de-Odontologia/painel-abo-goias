"""Filtro de período compartilhado entre as aplicações.

CME e Laboratório usam o mesmo widget de período
(``templates/partials/filtro_periodo.html``), mas cada um tinha a sua cópia da
lógica por trás dele. Aqui ela existe uma vez só.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models.query import QuerySet
from django.utils import timezone


def parse_data_iso(valor: str, fim_do_dia: bool = False) -> datetime | None:
    """Converte "aaaa-mm-dd" (formato de ``<input type="date">``) em datetime
    aware, ou None se inválido.

    ``fim_do_dia`` estica o horário até 23:59:59, para que o extremo superior
    de um intervalo inclua o dia inteiro em vez de parar na meia-noite.
    """

    if not valor:
        return None
    try:
        dt = datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        return None
    if fim_do_dia:
        dt = dt.replace(hour=23, minute=59, second=59)
    return timezone.make_aware(dt)


def filtrar_por_intervalo(
    queryset: QuerySet,
    campo: str,
    data_inicio: datetime | None,
    data_fim: datetime | None,
) -> QuerySet:
    """Recorta um queryset pelo intervalo de datas, no campo indicado.

    Serve tanto para ``DateTimeField`` (``data_hora``, ``data_emprestimo``,
    ``criado_em``) quanto para ``DateField`` (``previsao_entrega``,
    ``data_entrega``, ``data_faturamento``, ``data_vencimento``).

    A versão do Laboratório mantinha uma lista de quais campos eram datetime
    para, nos demais, comparar só com ``.date()``. Isso era desnecessário: o
    ``DateField.to_python`` do Django já converte um datetime aware para o fuso
    local e reduz à data antes de montar a query — verificado comparando o SQL
    gerado com e sem o ``.date()``, que sai idêntico. A lista foi removida em
    vez de reproduzida aqui; se alguém pensar em trazê-la de volta, o motivo de
    ela não ser necessária está neste parágrafo.
    """

    if data_inicio:
        queryset = queryset.filter(**{f"{campo}__gte": data_inicio})
    if data_fim:
        queryset = queryset.filter(**{f"{campo}__lte": data_fim})
    return queryset
