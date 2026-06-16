from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import render

from core.models import Aluno, OrigemDados, Turma
from core.integrations.eduq import EduqAPIError
from core.services.eduq_sync import sincronizar_localizacao_alunos_turma

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
        alunos = (
            Aluno.objects.filter(turma=turma)
            .exclude(origem=OrigemDados.EXEMPLO)
            .order_by("nome")
            if turma
            else Aluno.objects.none()
        )
        total_alunos = alunos.count()

        if turma is None:
            messages.error(request, "Selecione uma turma valida.")
        elif modelo is None:
            messages.error(request, "Selecione um modelo valido.")
        elif not modelo.disponivel:
            messages.error(request, "O modelo selecionado esta indisponivel.")
        elif total_alunos == 0:
            messages.error(request, "A turma selecionada nao possui alunos cadastrados.")
        else:
            if alunos.filter(Q(cidade="") | Q(uf="")).exists():
                try:
                    total_localizacoes = sincronizar_localizacao_alunos_turma(turma)
                    if total_localizacoes:
                        messages.info(
                            request,
                            f"Localizacao atualizada para {total_localizacoes} aluno(s) antes da geracao.",
                        )
                        alunos = (
                            Aluno.objects.filter(turma=turma)
                            .exclude(origem=OrigemDados.EXEMPLO)
                            .order_by("nome")
                        )
                except EduqAPIError:
                    messages.warning(
                        request,
                        "Nao foi possivel atualizar a localizacao dos alunos pelo Eduq agora.",
                    )
            alunos_sem_local = alunos.filter(Q(cidade="") | Q(uf="")).count()
            if alunos_sem_local:
                messages.warning(
                    request,
                    f"{alunos_sem_local} aluno(s) ainda estao sem localizacao cadastrada.",
                )
            arquivo = gerar_arquivo_identificadores(turma, modelo, alunos)
            resultado = {
                "total_alunos": total_alunos,
                "total_paginas": arquivo.total_paginas,
                "total_identificadores": arquivo.total_identificadores,
                "nome_arquivo": arquivo.caminho.name,
                "turma": turma,
                "modelo": modelo,
            }
            if arquivo.total_identificadores < total_alunos:
                messages.warning(
                    request,
                    "O modelo suporta ate 48 identificadores. O arquivo foi gerado com os 48 primeiros alunos em ordem alfabetica.",
                )
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
