from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .integrations.eduq import EduqAPIError
from .models import Aluno, Armario, Emprestimo, Material, Movimentacao, OrigemDados, Turma
from .services.eduq_sync import sincronizar_eduq


REGISTROS_POR_PAGINA = 10

STATUS_MOVIMENTACAO_OPCOES = (
    ("retirado", "Retirado"),
    ("pendente", "Nao retirado"),
    ("sem_status", "Sem status"),
)


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
            registro.status_label = "Nao retirado"
            registro.status_classe = "atrasado"
        else:
            registro.status_label = "Sem status"
            registro.status_classe = "emprestado"
        registro.material_resumo = registro.material.nome if registro.material else "Pacote legado"

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
    if not request.user.is_staff:
        return HttpResponseForbidden("Usuario sem permissao para sincronizar turmas.")

    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
    except EduqAPIError as exc:
        messages.error(request, f"Nao foi possivel sincronizar turmas: {exc}")
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

    armarios_queryset = Armario.objects.prefetch_related("estoques__material").order_by(
        "identificacao"
    )
    if not request.user.is_superuser:
        armarios_queryset = armarios_queryset.filter(
            itens_emprestados__emprestimo__coordenador_usuario=request.user
        ).distinct()
    if busca:
        armarios_queryset = armarios_queryset.filter(
            Q(identificacao__icontains=busca)
            | Q(localizacao__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(estoques__material__nome__icontains=busca)
            | Q(estoques__material__codigo__icontains=busca)
        ).distinct()

    armarios_lista = list(armarios_queryset)
    page_obj, query_string = paginar_queryset(request, armarios_lista)
    rows = []
    total_unidades = 0
    for armario in armarios_lista:
        estoques = list(armario.estoques.all())
        total_unidades += sum(estoque.quantidade for estoque in estoques)

    for armario in page_obj.object_list:
        estoques = list(armario.estoques.all())
        quantidade_total = sum(estoque.quantidade for estoque in estoques)
        materiais_resumo = ", ".join(estoque.material.nome for estoque in estoques[:3])
        if len(estoques) > 3:
            materiais_resumo += f" +{len(estoques) - 3}"

        rows.append(
            {
                "cells": [
                    {"primary": armario.identificacao, "secondary": armario.localizacao},
                    {"primary": len(estoques), "secondary": "materiais distintos"},
                    {"primary": quantidade_total, "secondary": "unidades em estoque"},
                    {"primary": materiais_resumo or "-", "secondary": armario.descricao},
                    {
                        "badge": "Ativo" if armario.ativo else "Inativo",
                        "badge_class": "badge-devolvido"
                        if armario.ativo
                        else "badge-atrasado",
                    },
                ]
            }
        )

    armarios_base = Armario.objects.all()
    if not request.user.is_superuser:
        armarios_base = armarios_base.filter(
            itens_emprestados__emprestimo__coordenador_usuario=request.user
        ).distinct()

    metricas = [
        {"label": "Armários", "value": armarios_base.count()},
        {"label": "Ativos", "value": armarios_base.filter(ativo=True).count()},
        {"label": "Unidades", "value": total_unidades},
        {"label": "Filtrados", "value": page_obj.paginator.count},
    ]

    return render(
        request,
        "core/listagem.html",
        {
            "usuario_logado": request.user,
            "titulo": "Armários",
            "subtitulo": "Veja os locais de guarda e o resumo de materiais disponíveis.",
            "section_label": "Estoque físico",
            "active_page": "armarios",
            "busca": busca,
            "metricas": metricas,
            "table_headers": ["Armário", "Materiais", "Quantidade", "Resumo", "Status"],
            "rows": rows,
            "page_obj": page_obj,
            "query_string": query_string,
            "empty_message": "Nenhum armário encontrado.",
        },
    )


@login_required
def materiais(request):
    busca = request.GET.get("q", "").strip()

    materiais_queryset = Material.objects.prefetch_related("kits", "armarios").order_by("nome")
    if not request.user.is_superuser:
        materiais_queryset = materiais_queryset.filter(
            itememprestimo__emprestimo__coordenador_usuario=request.user
        ).distinct()
    if busca:
        materiais_queryset = materiais_queryset.filter(
            Q(nome__icontains=busca)
            | Q(codigo__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(kits__nome__icontains=busca)
            | Q(armarios__identificacao__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, materiais_queryset)
    rows = []
    for material in page_obj.object_list:
        kits_material = list(material.kits.all())
        rows.append(
            {
                "cells": [
                    {"primary": material.nome, "secondary": material.codigo},
                    {
                        "primary": material.identificacao or material.get_unidade_medida_display(),
                        "secondary": material.rotulo_kit or f"minimo: {material.quantidade_minima}",
                    },
                    {
                        "primary": "Disponivel" if material.disponivel else "Indisponivel",
                        "secondary": "item emprestavel",
                    },
                    {
                        "primary": len(kits_material),
                        "secondary": "kits vinculados",
                    },
                    {
                        "badge": "Ativo" if material.ativo else "Inativo",
                        "badge_class": "badge-devolvido"
                        if material.ativo
                        else "badge-atrasado",
                    },
                ]
            }
        )

    materiais_base = Material.objects.all()
    if not request.user.is_superuser:
        materiais_base = materiais_base.filter(
            itememprestimo__emprestimo__coordenador_usuario=request.user
        ).distinct()

    metricas = [
        {"label": "Materiais", "value": materiais_base.count()},
        {"label": "Ativos", "value": materiais_base.filter(ativo=True).count()},
        {"label": "Disponiveis", "value": materiais_base.filter(disponivel=True).count()},
        {"label": "Filtrados", "value": page_obj.paginator.count},
    ]

    return render(
        request,
        "core/listagem.html",
        {
            "usuario_logado": request.user,
            "titulo": "Materiais",
            "subtitulo": "Consulte todos os materiais cadastrados para uso nas clínicas e laboratórios.",
            "section_label": "Catálogo da faculdade",
            "active_page": "materiais",
            "busca": busca,
            "metricas": metricas,
            "table_headers": ["Material", "Identificacao", "Disponibilidade", "Kits", "Status"],
            "rows": rows,
            "page_obj": page_obj,
            "query_string": query_string,
            "empty_message": "Nenhum material encontrado.",
        },
    )
