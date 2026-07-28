"""Paginação compartilhada entre as aplicações."""

from __future__ import annotations

from typing import Any

from django.core.paginator import Page, Paginator
from django.db.models.query import QuerySet
from django.http import HttpRequest


def paginar(
    request: HttpRequest, queryset: QuerySet[Any], por_pagina: int
) -> tuple[Page[Any], str]:
    """Pagina um queryset preservando os filtros atuais da query string.

    Devolve também a query string sem o parâmetro ``page``, que os templates de
    paginação reanexam a cada link — é o que faz busca e filtros sobreviverem à
    navegação entre páginas.

    ``por_pagina`` é explícito para que cada app continue dona da própria
    densidade de listagem.
    """

    parametros = request.GET.copy()
    parametros.pop("page", None)
    paginator = Paginator(queryset, por_pagina)
    return paginator.get_page(request.GET.get("page")), parametros.urlencode()
