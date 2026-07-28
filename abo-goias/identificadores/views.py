from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from gestao_cme.integrations.eduq import EduqAPIError
from gestao_cme.models import Aluno, OrigemDados, Turma
from gestao_cme.services.eduq_sync import (
    sincronizar_eduq,
    sincronizar_localizacao_alunos_turma,
)
from gestao_cme.utils import normalizar_texto

from .services.modelos import (
    buscar_modelo,
    caminho_arquivo_gerado,
    gerar_arquivo_identificadores,
    listar_modelos,
)


STATUS_TURMA_OPCOES = ("ativas", "finalizadas", "todas")


def _filtrar_turmas_status(queryset, status: str, hoje: date):
    """Filtra turmas por situacao.

    Uma turma e considerada *finalizada* quando tem data de finalizacao (vinda
    do Eduq) anterior a hoje; *ativa* nos demais casos (sem data ou data futura).
    """

    finalizadas = Q(data_fim__isnull=False, data_fim__lt=hoje)
    if status == "finalizadas":
        return queryset.filter(finalizadas)
    if status == "ativas":
        return queryset.exclude(finalizadas)
    return queryset


@login_required
def index(request: HttpRequest) -> HttpResponse:
    """Exibe e processa a geracao de identificadores por turma.

    No GET, monta a tela com turmas ativas e modelos PPTX disponiveis. No POST,
    valida turma e modelo, tenta atualizar localizacao de alunos sem cidade ou
    UF, gera o arquivo de identificadores e prepara o resumo do resultado para
    exibicao no template.
    """

    hoje = date.today()
    base_turmas = Turma.objects.exclude(origem=OrigemDados.EXEMPLO)
    status = request.GET.get("status", "ativas")
    if status not in STATUS_TURMA_OPCOES:
        status = "ativas"

    modelos = listar_modelos()
    turma_selecionada_id = (
        request.POST.get("turma", "") if request.method == "POST" else ""
    )
    modelo_selecionado_id = (
        request.POST.get("modelo", "") if request.method == "POST" else ""
    )
    resultado = None
    turma_selecionada = None
    alunos_turma = Aluno.objects.none()

    if request.method == "POST":
        turma = (
            base_turmas.filter(pk=turma_selecionada_id).first()
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
        turma_selecionada = turma

        if turma is None:
            messages.error(request, "Selecione uma turma valida.")
        elif modelo is None:
            messages.error(request, "Selecione um modelo valido.")
        elif not modelo.disponivel:
            messages.error(request, "O modelo selecionado esta indisponivel.")
        elif total_alunos == 0:
            messages.error(
                request, "A turma selecionada nao possui alunos cadastrados."
            )
        else:
            if alunos.filter(Q(cidade="") | Q(uf="")).exists():
                try:
                    total_localizacoes = sincronizar_localizacao_alunos_turma(turma)
                    if total_localizacoes:
                        messages.info(
                            request,
                            (
                                "Localizacao atualizada para "
                                f"{total_localizacoes} aluno(s) antes da geracao."
                            ),
                        )
                        alunos = (
                            Aluno.objects.filter(turma=turma)
                            .exclude(origem=OrigemDados.EXEMPLO)
                            .order_by("nome")
                        )
                except EduqAPIError:
                    messages.warning(
                        request,
                        (
                            "Nao foi possivel atualizar a localizacao dos alunos "
                            "agora."
                        ),
                    )
            alunos_sem_local = alunos.filter(Q(cidade="") | Q(uf="")).count()
            if alunos_sem_local:
                messages.warning(
                    request,
                    (
                        f"{alunos_sem_local} aluno(s) ainda estao sem "
                        "localizacao cadastrada."
                    ),
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
                    (
                        "O modelo suporta ate 48 identificadores. O arquivo foi "
                        "gerado com os 48 primeiros alunos em ordem alfabetica."
                    ),
                )
            messages.success(request, "Arquivo de identificadores gerado com sucesso.")

        if turma is not None:
            alunos_turma = alunos

    total_turmas = base_turmas.count()
    finalizadas_count = base_turmas.filter(
        data_fim__isnull=False, data_fim__lt=hoje
    ).count()
    ativas_count = total_turmas - finalizadas_count
    total_alunos_sinc = Aluno.objects.exclude(origem=OrigemDados.EXEMPLO).count()

    turmas = _filtrar_turmas_status(base_turmas, status, hoje).order_by("nome")[:30]

    return render(
        request,
        "identificadores/index.html",
        {
            "usuario_logado": request.user,
            "turmas": turmas,
            "modelos": modelos,
            "status": status,
            "status_opcoes": [
                ("ativas", "Ativas", ativas_count),
                ("finalizadas", "Finalizadas", finalizadas_count),
                ("todas", "Todas", total_turmas),
            ],
            "turma_selecionada_id": turma_selecionada_id,
            "turma_selecionada": turma_selecionada,
            "alunos_turma": alunos_turma,
            "modelo_selecionado_id": modelo_selecionado_id,
            "resultado": resultado,
            "hoje": hoje,
            "total_turmas": total_turmas,
            "ativas_count": ativas_count,
            "finalizadas_count": finalizadas_count,
            "total_alunos_sinc": total_alunos_sinc,
            "total_modelos": len(modelos),
            "total_modelos_disponiveis": sum(
                1 for modelo in modelos if modelo.disponivel
            ),
        },
    )


@login_required
def buscar_turmas(request: HttpRequest) -> HttpResponse:
    """Fragmento HTMX com as turmas filtradas por busca e situacao.

    Consumido pelo campo de pesquisa de turma. Recebe ``q`` (texto) e ``status``
    (ativas/finalizadas/todas) e devolve a lista de resultados clicaveis.
    """

    hoje = date.today()
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "ativas")
    if status not in STATUS_TURMA_OPCOES:
        status = "ativas"

    turmas = _filtrar_turmas_status(
        Turma.objects.exclude(origem=OrigemDados.EXEMPLO), status, hoje
    )
    if q:
        turmas = turmas.filter(
            Q(nome_normalizado__icontains=normalizar_texto(q))
            | Q(codigo__icontains=q)
        )
    turmas = turmas.order_by("nome")[:30]

    return render(
        request,
        "identificadores/partials/_turma_results.html",
        {"turmas": turmas, "busca": q, "hoje": hoje},
    )


@login_required
def turma_alunos(request: HttpRequest, turma_id: int) -> HttpResponse:
    """Fragmento HTMX com os dados da turma e seus alunos sincronizados (Eduq).

    Exibido ao selecionar uma turma na busca. Traz o resumo da turma e a lista
    de alunos com a localizacao (cidade/UF) retornada pelo Eduq, alem de um
    campo oculto ``turma`` que alimenta o formulario de geracao.
    """

    turma = get_object_or_404(
        Turma.objects.exclude(origem=OrigemDados.EXEMPLO), pk=turma_id
    )
    alunos = (
        Aluno.objects.filter(turma=turma)
        .exclude(origem=OrigemDados.EXEMPLO)
        .order_by("nome")
    )
    sem_localizacao = alunos.filter(Q(cidade="") | Q(uf="")).count()

    return render(
        request,
        "identificadores/partials/_turma_alunos.html",
        {
            "turma": turma,
            "alunos": alunos,
            "total_alunos": alunos.count(),
            "sem_localizacao": sem_localizacao,
            "hoje": date.today(),
        },
    )


@login_required
def sincronizar(request: HttpRequest) -> HttpResponse:
    """Sincroniza turmas e alunos com o Eduq e redireciona de volta ao app."""

    if request.method != "POST":
        return redirect("identificadores:index")

    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=True,
            sincronizar_alunos=True,
        )
    except EduqAPIError as exc:
        messages.error(request, f"Não foi possível atualizar turmas e alunos agora: {exc}")
    else:
        erros_turmas = len(resultado.turmas.erros)
        erros_alunos = len(resultado.alunos.erros)
        msg = (
            f"Turmas: {resultado.turmas.criados} criadas, "
            f"{resultado.turmas.atualizados} atualizadas"
            + (f", {erros_turmas} erro(s)" if erros_turmas else "")
            + f". Alunos: {resultado.alunos.criados} criados, "
            f"{resultado.alunos.atualizados} atualizados"
            + (f", {erros_alunos} erro(s)" if erros_alunos else "")
            + "."
        )
        messages.success(request, msg)

    return redirect("identificadores:index")


@login_required
def baixar(request: HttpRequest, nome_arquivo: str) -> FileResponse:
    """Entrega ao usuario um arquivo PPTX de identificadores ja gerado.

    Valida o nome recebido, confirma que o arquivo existe na area de geracao e
    retorna uma resposta de download. Quando o caminho e invalido ou inexistente,
    responde com erro 404.
    """

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
        content_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
    )
