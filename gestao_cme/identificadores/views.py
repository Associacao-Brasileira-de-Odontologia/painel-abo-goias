from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import OrigemDados, Turma

from .services.modelos import listar_modelos


@login_required
def index(request):
    turmas = (
        Turma.objects.exclude(origem=OrigemDados.EXEMPLO)
        .filter(ativo=True)
        .order_by("nome")
    )
    modelos = listar_modelos()

    return render(
        request,
        "identificadores/index.html",
        {
            "usuario_logado": request.user,
            "turmas": turmas,
            "modelos": modelos,
            "total_turmas": turmas.count(),
            "total_modelos": len(modelos),
            "total_modelos_disponiveis": sum(1 for modelo in modelos if modelo.disponivel),
        },
    )
