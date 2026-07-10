"""Infraestrutura de grupos de acesso.

Define os grupos padrão e um decorator para restringir views a membros de
grupos específicos. Nenhuma view do projeto usa ``requer_grupo`` ainda — as
regras de quem pode fazer o quê (enviar contrato ao Dental Office, excluir
movimentação, etc.) serão decididas e aplicadas numa fase futura. Este
módulo só prepara o mecanismo para que isso possa ser feito sem reescrever
a checagem de permissão em cada view.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

GRUPO_RECEPCAO = "recepcao"
GRUPO_COORDENACAO = "coordenacao"
GRUPO_GESTAO = "gestao"

GRUPOS_PADRAO = (GRUPO_RECEPCAO, GRUPO_COORDENACAO, GRUPO_GESTAO)


def requer_grupo(
    *nomes_grupos: str,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """Restringe a view a superusuários ou membros de um dos grupos informados.

    Aplica ``login_required`` automaticamente. Usuário autenticado fora dos
    grupos exigidos recebe ``PermissionDenied`` (403).
    """

    def decorator(
        view_func: Callable[..., HttpResponse],
    ) -> Callable[..., HttpResponse]:
        @wraps(view_func)
        @login_required
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if request.user.groups.filter(name__in=nomes_grupos).exists():
                return view_func(request, *args, **kwargs)
            raise PermissionDenied

        return wrapper

    return decorator
