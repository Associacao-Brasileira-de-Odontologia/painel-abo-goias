from django.contrib import admin

from .models import (
    Aluno,
    Armario,
    Emprestimo,
    EstoqueArmario,
    ItemEmprestimo,
    Kit,
    KitMaterial,
    Material,
    Turma,
)


@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "curso", "data_inicio", "data_fim", "ativo")
    list_filter = ("ativo", "curso")
    search_fields = ("codigo", "nome", "curso")


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ("nome", "matricula", "turma", "email", "telefone", "ativo")
    list_filter = ("ativo", "turma")
    search_fields = ("nome", "matricula", "cpf", "email")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "unidade_medida", "quantidade_minima", "ativo")
    list_filter = ("ativo", "unidade_medida")
    search_fields = ("codigo", "nome", "descricao")


class KitMaterialInline(admin.TabularInline):
    model = KitMaterial
    extra = 1
    autocomplete_fields = ("material",)


@admin.register(Kit)
class KitAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "ativo")
    list_filter = ("ativo",)
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
        "data_emprestimo",
        "data_prevista_devolucao",
        "status",
    )
    list_filter = ("status", "kit", "data_emprestimo")
    search_fields = (
        "aluno__nome",
        "aluno__matricula",
        "kit__nome",
        "coordenador",
        "observacoes",
    )
    autocomplete_fields = ("aluno", "kit")
    date_hierarchy = "data_emprestimo"
    inlines = (ItemEmprestimoInline,)


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

