from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import render

from core.models import Aluno, OrigemDados, Turma

from .services.modelos import (
    buscar_modelo,
    caminho_arquivo_gerado,
    gerar_arquivo_identificadores,
    listar_modelos,
)


@login_required
def index(request):
    turmas = (
        Turma.objects.exclude(origem=OrigemDados.EXEMPLO)
        .filter(ativo=True)
        .order_by("nome")
    )
    modelos = listar_modelos()
    turma_selecionada_id = request.POST.get("turma", "") if request.method == "POST" else ""
    modelo_selecionado_id = request.POST.get("modelo", "") if request.method == "POST" else ""
    resultado = None

    if request.method == "POST":
        turma = (
            turmas.filter(pk=turma_selecionada_id).first()
            if turma_selecionada_id.isdigit()
            else None
        )
        modelo = buscar_modelo(modelo_selecionado_id)
        total_alunos = (
            Aluno.objects.filter(turma=turma).exclude(origem=OrigemDados.EXEMPLO).count()
            if turma
            else 0
        )

        if turma is None:
            messages.error(request, "Selecione uma turma valida.")
        elif modelo is None:
            messages.error(request, "Selecione um modelo valido.")
        elif not modelo.disponivel:
            messages.error(request, "O modelo selecionado esta indisponivel.")
        elif total_alunos == 0:
            messages.error(request, "A turma selecionada nao possui alunos cadastrados.")
        else:
            arquivo = gerar_arquivo_identificadores(turma, modelo)
            resultado = {
                "total_alunos": total_alunos,
                "total_paginas": total_alunos,
                "nome_arquivo": arquivo.name,
                "turma": turma,
                "modelo": modelo,
            }
            messages.success(request, "Arquivo de identificadores gerado com sucesso.")

    return render(
        request,
        "identificadores/index.html",
        {
            "usuario_logado": request.user,
            "turmas": turmas,
            "modelos": modelos,
            "turma_selecionada_id": turma_selecionada_id,
            "modelo_selecionado_id": modelo_selecionado_id,
            "resultado": resultado,
            "total_turmas": turmas.count(),
            "total_modelos": len(modelos),
            "total_modelos_disponiveis": sum(1 for modelo in modelos if modelo.disponivel),
        },
    )


@login_required
def baixar(request, nome_arquivo):
    try:
        caminho = caminho_arquivo_gerado(nome_arquivo)
    except ValueError as exc:
        raise Http404("Arquivo nao encontrado.") from exc
    if not caminho.exists():
        raise Http404("Arquivo nao encontrado.")
    return FileResponse(
        caminho.open("rb"),
        as_attachment=True,
        filename=caminho.name,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
