from django.contrib import admin

from .models import AlunoLab, Equipe, Laboratorio, Moldagem, Paciente, PedidoMaterial


@admin.register(Equipe)
class EquipeAdmin(admin.ModelAdmin):
    list_display = ("nome", "coordenador", "whatsapp", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "coordenador")


@admin.register(Laboratorio)
class LaboratorioAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "whatsapp", "email", "cnpj", "ativo")
    list_filter = ("ativo", "equipes")
    search_fields = ("nome", "cnpj", "email")
    filter_horizontal = ("equipes",)


@admin.register(AlunoLab)
class AlunoLabAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "celular",
        "id_dental",
        "origem",
        "ultima_sincronizacao",
        "ativo",
    )
    list_filter = ("ativo", "origem")
    search_fields = ("nome", "celular", "id_dental")
    readonly_fields = ("ultima_sincronizacao",)


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "celular",
        "id_dental",
        "processo_aberto",
        "data_previsao_retorno",
        "ultima_sincronizacao",
        "ativo",
    )
    list_filter = ("ativo", "processo_aberto", "origem")
    search_fields = ("nome", "celular", "id_dental")
    readonly_fields = ("ultima_sincronizacao",)
    date_hierarchy = "data_previsao_retorno"


@admin.register(PedidoMaterial)
class PedidoMaterialAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "paciente",
        "aluno",
        "laboratorio",
        "equipe",
        "previsao_entrega",
        "data_envio",
        "entregue",
        "status",
        "faturado_paciente",
        "faturado_lab",
    )
    list_filter = (
        "status",
        "entregue",
        "faturado_paciente",
        "faturado_lab",
        "laboratorio",
        "equipe",
    )
    search_fields = (
        "paciente__nome",
        "aluno__nome",
        "laboratorio__nome",
        "descricao_servico",
    )
    readonly_fields = ("status",)
    date_hierarchy = "previsao_entrega"
    autocomplete_fields = ("paciente", "aluno", "laboratorio", "equipe")


@admin.register(Moldagem)
class MoldagemAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "paciente",
        "aluno",
        "faturado",
        "entregue",
        "convertida",
        "criado_em",
    )
    list_filter = ("faturado", "entregue", "ativo")
    search_fields = ("paciente__nome", "aluno__nome")
    readonly_fields = ("pedido_material",)
    autocomplete_fields = ("paciente", "aluno")

    @admin.display(boolean=True, description="Convertida")
    def convertida(self, obj):
        return obj.convertida
