from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .integrations.eduq import EduqAPIError
from .models import Abrigo, Aluno, Armario, Emprestimo, Kit, Material, Movimentacao, OrigemDados, Turma
from .services.eduq_sync import sincronizar_eduq


REGISTROS_POR_PAGINA = 10

STATUS_MOVIMENTACAO_OPCOES = (
    ("retirado", "Retirado"),
    ("pendente", "Não retirado"),
    ("sem_status", "Sem status"),
)


def healthcheck(request):
    return HttpResponse("ok", content_type="text/plain")


def paginar_queryset(request, queryset):
    query_params = request.GET.copy()
    query_params.pop("page", None)
    paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get("page"))

    return page_obj, query_params.urlencode()


def emprestimos_visiveis(request):
    queryset = Emprestimo.objects.exclude(
        Q(aluno__origem=OrigemDados.EXEMPLO)
        | Q(aluno__turma__origem=OrigemDados.EXEMPLO)
    )
    if request.user.is_superuser:
        return queryset
    return queryset.filter(coordenador_usuario=request.user)


@login_required
def home(request):
    busca = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    movimentacao = request.GET.get("movimentacao", "").strip()

    movimentacoes = (
        Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)
        .select_related("aluno", "turma", "material")
        .order_by("-data_hora", "-id")
    )

    if status == "retirado":
        movimentacoes = movimentacoes.filter(retirado=True)
    elif status == "pendente":
        movimentacoes = movimentacoes.filter(retirado=False)
    elif status == "sem_status":
        movimentacoes = movimentacoes.filter(retirado__isnull=True)

    if movimentacao in Movimentacao.Tipo.values:
        movimentacoes = movimentacoes.filter(tipo=movimentacao)

    if busca:
        movimentacoes = movimentacoes.filter(
            Q(aluno_nome__icontains=busca)
            | Q(aluno_codigo_externo__icontains=busca)
            | Q(turma_nome__icontains=busca)
            | Q(pacote_codigo__icontains=busca)
            | Q(arquivo_origem__icontains=busca)
            | Q(material__nome__icontains=busca)
            | Q(material__codigo__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, movimentacoes)
    status_label = dict(STATUS_MOVIMENTACAO_OPCOES).get(status, "Todos")
    movimentacao_label = dict(Movimentacao.Tipo.choices).get(movimentacao, "Todas")

    for registro in page_obj.object_list:
        if registro.retirado is True:
            registro.status_label = "Retirado"
            registro.status_classe = "devolvido"
        elif registro.retirado is False:
            registro.status_label = "Não retirado"
            registro.status_classe = "atrasado"
        else:
            registro.status_label = "Sem status"
            registro.status_classe = "emprestado"
        registro.material_resumo = registro.material.nome if registro.material else "Pacote"

    metricas = Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO).aggregate(
        total=Count("id"),
        saidas=Count("id", filter=Q(tipo=Movimentacao.Tipo.SAIDA)),
        entradas=Count("id", filter=Q(tipo=Movimentacao.Tipo.ENTRADA)),
        pendentes=Count("id", filter=Q(retirado=False)),
    )

    return render(
        request,
        "core/home.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "status_atual": status,
            "status_label": status_label,
            "status_opcoes": STATUS_MOVIMENTACAO_OPCOES,
            "movimentacao_atual": movimentacao,
            "movimentacao_label": movimentacao_label,
            "movimentacao_opcoes": Movimentacao.Tipo.choices,
            "movimentacoes": page_obj.object_list,
            "metricas": metricas,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def alunos_por_turma(request):
    busca = request.GET.get("q", "").strip()
    turma_id = request.GET.get("turma", "").strip()

    alunos = (
        Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
        .exclude(turma__origem=OrigemDados.EXEMPLO)
        .select_related("turma")
        .order_by("turma__nome", "nome")
    )
    if not request.user.is_superuser:
        alunos = alunos.filter(emprestimos__coordenador_usuario=request.user).distinct()
    if turma_id.isdigit():
        alunos = alunos.filter(turma_id=turma_id)
    if busca:
        alunos = alunos.filter(
            Q(nome__icontains=busca)
            | Q(matricula__icontains=busca)
            | Q(email__icontains=busca)
            | Q(turma__nome__icontains=busca)
            | Q(turma__codigo__icontains=busca)
        )

    page_obj, query_string = paginar_queryset(request, alunos)
    rows = [
        {
            "cells": [
                {
                    "primary": aluno.turma.nome if aluno.turma else "Sem turma",
                    "secondary": aluno.turma.codigo if aluno.turma else "",
                },
                {"primary": aluno.nome, "secondary": aluno.matricula},
                {"primary": aluno.email or "-", "secondary": aluno.telefone or ""},
                {
                    "badge": "Ativo" if aluno.ativo else "Inativo",
                    "badge_class": "badge-devolvido" if aluno.ativo else "badge-atrasado",
                },
            ]
        }
        for aluno in page_obj.object_list
    ]

    turmas = Turma.objects.exclude(origem=OrigemDados.EXEMPLO).order_by("nome")
    if not request.user.is_superuser:
        turmas = turmas.filter(alunos__emprestimos__coordenador_usuario=request.user).distinct()

    alunos_base = Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
    turmas_base = Turma.objects.exclude(origem=OrigemDados.EXEMPLO)
    if not request.user.is_superuser:
        alunos_base = alunos_base.filter(emprestimos__coordenador_usuario=request.user).distinct()
        turmas_base = turmas_base.filter(alunos__emprestimos__coordenador_usuario=request.user).distinct()

    ultima_sincronizacao_alunos = alunos_base.aggregate(
        ultima=Max("ultima_sincronizacao")
    )["ultima"]
    ultima_sincronizacao_turmas = turmas_base.aggregate(
        ultima=Max("ultima_sincronizacao")
    )["ultima"]
    datas_sincronizacao = [
        data
        for data in (ultima_sincronizacao_alunos, ultima_sincronizacao_turmas)
        if data
    ]
    ultima_sincronizacao = max(datas_sincronizacao) if datas_sincronizacao else None

    metricas = [
        {"label": "Alunos", "value": alunos_base.count()},
        {"label": "Turmas", "value": turmas_base.count()},
        {"label": "Ativos", "value": alunos_base.filter(ativo=True).count()},
        {"label": "Filtrados", "value": page_obj.paginator.count},
    ]

    return render(
        request,
        "core/listagem.html",
        {
            "usuario_logado": request.user,
            "titulo": "Alunos por turma",
            "subtitulo": "Consulte os alunos vinculados a cada turma da pós-graduação.",
            "section_label": "Cadastros acadêmicos",
            "active_page": "alunos",
            "busca": busca,
            "metricas": metricas,
            "table_headers": ["Turma", "Aluno", "Contato", "Status"],
            "rows": rows,
            "page_obj": page_obj,
            "query_string": query_string,
            "empty_message": "Nenhum aluno encontrado.",
            "sync_action_url": "sincronizar_turmas_eduq",
            "ultima_sincronizacao": ultima_sincronizacao,
            "filter_select": {
                "name": "turma",
                "label": "Turma",
                "value": turma_id,
                "options": [
                    {"value": str(turma.pk), "label": f"{turma.codigo} - {turma.nome}"}
                    for turma in turmas
                ],
            },
        },
    )


@login_required
@require_POST
def sincronizar_turmas_eduq(request):
    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
    except EduqAPIError as exc:
        messages.error(request, f"Não foi possível sincronizar turmas: {exc}")
    else:
        messages.success(
            request,
            "Turmas sincronizadas: "
            f"{resultado.turmas.criados} criadas, "
            f"{resultado.turmas.atualizados} atualizadas, "
            f"{len(resultado.turmas.erros)} erro(s).",
        )

    return redirect("alunos_por_turma")


@login_required
def armarios(request):
    busca = request.GET.get("q", "").strip()
    ocupacao = request.GET.get("ocupacao", "").strip()

    abrigos = Abrigo.objects.exclude(origem=OrigemDados.EXEMPLO).order_by("identificador")
    if ocupacao == "ocupado":
        abrigos = abrigos.filter(ocupado=True)
    elif ocupacao == "livre":
        abrigos = abrigos.filter(ocupado=False)
    if busca:
        abrigos = abrigos.filter(identificador__icontains=busca)

    page_obj, query_string = paginar_queryset(request, abrigos)
    abrigos_base = Abrigo.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": abrigos_base.count(),
        "ocupados": abrigos_base.filter(ocupado=True).count(),
        "livres": abrigos_base.filter(ocupado=False).count(),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "core/armarios.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "ocupacao_atual": ocupacao,
            "ocupacao_label": {"ocupado": "Ocupados", "livre": "Livres"}.get(
                ocupacao, "Todos"
            ),
            "metricas": metricas,
            "abrigos": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def materiais(request):
    busca = request.GET.get("q", "").strip()
    disponibilidade = request.GET.get("disponibilidade", "").strip()

    materiais_queryset = (
        Material.objects.exclude(origem=OrigemDados.EXEMPLO)
        .prefetch_related("kits")
        .order_by("nome", "identificacao")
    )
    if disponibilidade == "disponivel":
        materiais_queryset = materiais_queryset.filter(disponivel=True)
    elif disponibilidade == "indisponivel":
        materiais_queryset = materiais_queryset.filter(disponivel=False)
    if busca:
        materiais_queryset = materiais_queryset.filter(
            Q(nome__icontains=busca)
            | Q(codigo__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(identificacao__icontains=busca)
            | Q(rotulo_kit__icontains=busca)
            | Q(kits__nome__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, materiais_queryset)
    materiais_base = Material.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": materiais_base.count(),
        "ativos": materiais_base.filter(ativo=True).count(),
        "disponiveis": materiais_base.filter(disponivel=True).count(),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "core/materiais.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "disponibilidade_atual": disponibilidade,
            "disponibilidade_label": {
                "disponivel": "Disponíveis",
                "indisponivel": "Indisponíveis",
            }.get(disponibilidade, "Todos"),
            "metricas": metricas,
            "materiais": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def kits(request):
    busca = request.GET.get("q", "").strip()

    kits_queryset = (
        Kit.objects.exclude(origem=OrigemDados.EXEMPLO)
        .prefetch_related("itens__material")
        .order_by("nome")
    )
    if busca:
        kits_queryset = kits_queryset.filter(
            Q(nome__icontains=busca)
            | Q(codigo__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(itens__material__nome__icontains=busca)
            | Q(itens__material__identificacao__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, kits_queryset)
    for kit in page_obj.object_list:
        itens = list(kit.itens.all())
        kit.total_materiais = len(itens)
        kit.materiais_disponiveis = sum(1 for item in itens if item.material.disponivel)
        kit.materiais_resumo = ", ".join(
            item.material.identificacao or item.material.nome for item in itens[:4]
        )
        if len(itens) > 4:
            kit.materiais_resumo += f" +{len(itens) - 4}"

    kits_base = Kit.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": kits_base.count(),
        "ativos": kits_base.filter(ativo=True).count(),
        "quantidade": sum(kit.quantidade for kit in kits_base),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "core/kits.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "metricas": metricas,
            "kits": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )
