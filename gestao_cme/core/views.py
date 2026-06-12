from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render

from .models import Aluno, Armario, Emprestimo, Material, Turma


REGISTROS_POR_PAGINA = 10


def paginar_queryset(request, queryset):
    query_params = request.GET.copy()
    query_params.pop("page", None)
    paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get("page"))

    return page_obj, query_params.urlencode()


def emprestimos_visiveis(request):
    queryset = Emprestimo.objects.all()
    if request.user.is_superuser:
        return queryset
    return queryset.filter(coordenador_usuario=request.user)


@login_required
def home(request):
    busca = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    emprestimos = (
        emprestimos_visiveis(request)
        .select_related("aluno", "aluno__turma", "kit")
        .prefetch_related("itens__material", "itens__armario")
        .all()
    )

    if status in Emprestimo.Status.values:
        emprestimos = emprestimos.filter(status=status)

    if busca:
        emprestimos = emprestimos.filter(
            Q(aluno__nome__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
            | Q(aluno__turma__nome__icontains=busca)
            | Q(kit__nome__icontains=busca)
            | Q(kit__codigo__icontains=busca)
            | Q(coordenador__icontains=busca)
            | Q(itens__material__nome__icontains=busca)
            | Q(itens__material__codigo__icontains=busca)
        ).distinct()

    emprestimos = list(emprestimos[:15])
    status_label = dict(Emprestimo.Status.choices).get(status, "Todos")

    for emprestimo in emprestimos:
        itens = list(emprestimo.itens.all())
        emprestimo.total_itens = sum(item.quantidade for item in itens)
        emprestimo.materiais_resumo = ", ".join(
            f"{item.quantidade}x {item.material.nome}" for item in itens[:3]
        )
        if len(itens) > 3:
            emprestimo.materiais_resumo += f" +{len(itens) - 3}"
        emprestimo.status_classe = emprestimo.status.lower()

    metricas = emprestimos_visiveis(request).aggregate(
        total=Count("id"),
        emprestados=Count("id", filter=Q(status=Emprestimo.Status.EMPRESTADO)),
        atrasados=Count("id", filter=Q(status=Emprestimo.Status.ATRASADO)),
        devolvidos=Count("id", filter=Q(status=Emprestimo.Status.DEVOLVIDO)),
    )

    return render(
        request,
        "core/home.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "status_atual": status,
            "status_label": status_label,
            "status_opcoes": Emprestimo.Status.choices,
            "emprestimos": emprestimos,
            "metricas": metricas,
        },
    )


@login_required
def alunos_por_turma(request):
    busca = request.GET.get("q", "").strip()
    turma_id = request.GET.get("turma", "").strip()

    alunos = Aluno.objects.select_related("turma").order_by("turma__nome", "nome")
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

    turmas = Turma.objects.order_by("nome")
    if not request.user.is_superuser:
        turmas = turmas.filter(alunos__emprestimos__coordenador_usuario=request.user).distinct()

    alunos_base = Aluno.objects.all()
    turmas_base = Turma.objects.all()
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
        armarios_material = list(material.armarios.all())
        kits_material = list(material.kits.all())
        rows.append(
            {
                "cells": [
                    {"primary": material.nome, "secondary": material.codigo},
                    {
                        "primary": material.get_unidade_medida_display(),
                        "secondary": f"mínimo: {material.quantidade_minima}",
                    },
                    {
                        "primary": len(armarios_material),
                        "secondary": "armários com estoque",
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
        {"label": "Kits", "value": materiais_base.filter(kits__isnull=False).distinct().count()},
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
            "table_headers": ["Material", "Unidade", "Armários", "Kits", "Status"],
            "rows": rows,
            "page_obj": page_obj,
            "query_string": query_string,
            "empty_message": "Nenhum material encontrado.",
        },
    )
