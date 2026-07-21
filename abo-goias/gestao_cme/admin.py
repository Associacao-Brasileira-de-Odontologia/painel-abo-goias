from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db.models.query import QuerySet
from django.http import HttpRequest

from .models import (
    Abrigo,
    Aluno,
    Armario,
    Emprestimo,
    EstoqueArmario,
    ItemEmprestimo,
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    RegistroAuditoriaMovimentacao,
    Turma,
)


@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nome",
        "curso",
        "origem",
        "ultima_sincronizacao",
        "data_inicio",
        "data_fim",
        "ativo",
    )
    list_filter = ("ativo", "origem", "curso")
    search_fields = ("codigo", "nome", "curso")


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "matricula",
        "turma",
        "email",
        "telefone",
        "cidade",
        "uf",
        "origem",
        "ultima_sincronizacao",
        "ativo",
    )
    list_filter = ("ativo", "origem", "turma", "uf")
    search_fields = ("nome", "matricula", "cpf", "email", "cidade", "uf")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nome",
        "identificacao",
        "disponivel",
        "origem",
        "unidade_medida",
        "ativo",
    )
    list_filter = ("ativo", "disponivel", "origem", "unidade_medida")
    search_fields = ("codigo", "nome", "descricao", "identificacao", "rotulo_kit")


class KitMaterialInline(admin.TabularInline):
    model = KitMaterial
    extra = 1
    autocomplete_fields = ("material",)


@admin.register(Kit)
class KitAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "quantidade", "origem", "ativo")
    list_filter = ("ativo", "origem")
    search_fields = ("codigo", "nome", "descricao")
    inlines = (KitMaterialInline,)


class EstoqueArmarioInline(admin.TabularInline):
    model = EstoqueArmario
    extra = 1
    autocomplete_fields = ("material",)


@admin.register(Armario)
class ArmarioAdmin(admin.ModelAdmin):
    list_display = ("identificacao", "localizacao", "ativo")
    list_filter = ("ativo", "localizacao")
    search_fields = ("identificacao", "localizacao", "descricao")
    inlines = (EstoqueArmarioInline,)


@admin.register(Abrigo)
class AbrigoAdmin(admin.ModelAdmin):
    list_display = (
        "identificador",
        "ocupado",
        "origem",
        "ultima_sincronizacao",
        "ativo",
    )
    list_filter = ("ocupado", "origem", "ativo")
    search_fields = ("identificador",)


@admin.register(KitMaterial)
class KitMaterialAdmin(admin.ModelAdmin):
    list_display = ("kit", "material", "quantidade")
    list_filter = ("kit",)
    search_fields = ("kit__nome", "kit__codigo", "material__nome", "material__codigo")
    autocomplete_fields = ("kit", "material")


@admin.register(EstoqueArmario)
class EstoqueArmarioAdmin(admin.ModelAdmin):
    list_display = ("armario", "material", "quantidade")
    list_filter = ("armario",)
    search_fields = ("armario__identificacao", "material__nome", "material__codigo")
    autocomplete_fields = ("armario", "material")


class ItemEmprestimoInline(admin.TabularInline):
    model = ItemEmprestimo
    extra = 1
    autocomplete_fields = ("material", "armario")


@admin.register(Emprestimo)
class EmprestimoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "aluno",
        "kit",
        "coordenador",
        "coordenador_usuario",
        "data_emprestimo",
        "data_prevista_devolucao",
        "status",
    )
    list_filter = ("status", "kit", "coordenador_usuario", "data_emprestimo")
    search_fields = (
        "aluno__nome",
        "aluno__matricula",
        "kit__nome",
        "coordenador",
        "coordenador_usuario__username",
        "coordenador_usuario__first_name",
        "coordenador_usuario__last_name",
        "observacoes",
    )
    autocomplete_fields = ("aluno", "kit", "coordenador_usuario")
    date_hierarchy = "data_emprestimo"
    inlines = (ItemEmprestimoInline,)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Emprestimo]:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(coordenador_usuario=request.user)

    def save_model(
        self, request: HttpRequest, obj: Emprestimo, form: Any, change: bool
    ) -> None:
        if not obj.coordenador_usuario_id:
            obj.coordenador_usuario = request.user
        if not obj.coordenador:
            obj.coordenador = request.user.get_full_name() or request.user.username
        super().save_model(request, obj, form, change)


@admin.register(ItemEmprestimo)
class ItemEmprestimoAdmin(admin.ModelAdmin):
    list_display = ("emprestimo", "material", "armario", "quantidade")
    list_filter = ("armario", "material")
    search_fields = (
        "emprestimo__aluno__nome",
        "material__nome",
        "material__codigo",
        "armario__identificacao",
    )
    autocomplete_fields = ("emprestimo", "material", "armario")

    def get_queryset(self, request: HttpRequest) -> QuerySet[ItemEmprestimo]:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(emprestimo__coordenador_usuario=request.user)


@admin.register(Movimentacao)
class MovimentacaoAdmin(admin.ModelAdmin):
    list_display = (
        "data_hora",
        "tipo",
        "aluno_nome",
        "turma_nome",
        "pacote_codigo",
        "retirado",
        "arquivo_origem",
    )
    list_filter = ("tipo", "retirado", "arquivo_origem", "origem")
    search_fields = (
        "aluno_nome",
        "aluno_codigo_externo",
        "turma_nome",
        "pacote_codigo",
        "material__nome",
        "material__codigo",
    )
    autocomplete_fields = ("aluno", "turma", "material")
    date_hierarchy = "data_hora"


@admin.register(RegistroAuditoriaMovimentacao)
class RegistroAuditoriaMovimentacaoAdmin(admin.ModelAdmin):
    """Trilha somente leitura — os registros são gravados pelas views, nunca
    pelo Admin, então não faz sentido permitir criar/editar por aqui."""

    list_display = ("criado_em", "acao", "pacote_codigo", "aluno_nome", "usuario")
    list_filter = ("acao",)
    search_fields = ("pacote_codigo", "aluno_nome", "usuario__username")
    date_hierarchy = "criado_em"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Any | None = None
    ) -> bool:
        return False
