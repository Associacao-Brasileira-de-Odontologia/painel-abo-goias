from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def perfil(request: HttpRequest) -> HttpResponse:
    """Exibe os dados da conta do usuário autenticado."""

    return render(request, "auth/perfil.html")
