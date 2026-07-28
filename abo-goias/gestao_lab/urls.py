from django.urls import path

from . import views

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="lab_dashboard"),
    # Pedidos de material
    path("pedidos/", views.acompanhamento_pedidos, name="lab_pedidos"),
    path("pedidos/novo/", views.criar_pedido, name="lab_criar_pedido"),
    path(
        "pedidos/faturamento/",
        views.pedidos_faturamento,
        name="lab_pedidos_faturamento",
    ),
    path("pedidos/<int:pk>/", views.detalhe_pedido, name="lab_detalhe_pedido"),
    path("pedidos/<int:pk>/marcar-envio/", views.marcar_envio, name="lab_marcar_envio"),
    path(
        "pedidos/<int:pk>/marcar-entrega/",
        views.marcar_entrega,
        name="lab_marcar_entrega",
    ),
    path(
        "pedidos/<int:pk>/faturamento/",
        views.atualizar_faturamento,
        name="lab_atualizar_faturamento",
    ),
    path(
        "pedidos/<int:pk>/alternar-faturado-paciente/",
        views.alternar_faturado_paciente,
        name="lab_alternar_faturado_paciente",
    ),
    path(
        "pedidos/<int:pk>/alternar-faturado-lab/",
        views.alternar_faturado_lab,
        name="lab_alternar_faturado_lab",
    ),
    # Moldagens
    path("moldagens/", views.moldagens, name="lab_moldagens"),
    path("moldagens/nova/", views.criar_moldagem, name="lab_criar_moldagem"),
    path(
        "moldagens/<int:pk>/converter/",
        views.converter_moldagem,
        name="lab_converter_moldagem",
    ),
    path(
        "moldagens/<int:pk>/alternar-faturado/",
        views.alternar_faturado_moldagem,
        name="lab_alternar_faturado_moldagem",
    ),
    path(
        "moldagens/<int:pk>/alternar-entregue/",
        views.alternar_entregue_moldagem,
        name="lab_alternar_entregue_moldagem",
    ),
    # Laboratórios
    path("laboratorios/", views.laboratorios, name="lab_laboratorios"),
    path("laboratorios/novo/", views.criar_laboratorio, name="lab_criar_laboratorio"),
    path(
        "laboratorios/<int:pk>/editar/",
        views.editar_laboratorio,
        name="lab_editar_laboratorio",
    ),
    # Equipes
    path("equipes/", views.equipes, name="lab_equipes"),
    path("equipes/nova/", views.criar_equipe, name="lab_criar_equipe"),
    path("equipes/<int:pk>/editar/", views.editar_equipe, name="lab_editar_equipe"),
    # Alunos (Eduq)
    path("alunos/", views.alunos_lab, name="lab_alunos"),
    # Pacientes (Dental Office)
    path("pacientes/", views.pacientes, name="lab_pacientes"),
    path(
        "pacientes/<str:id_dental>/importar/",
        views.importar_paciente_dental,
        name="lab_importar_paciente",
    ),
    # Sincronização Dental Office
    path("pedidos/<int:pk>/excluir/", views.excluir_pedido, name="lab_excluir_pedido"),
    path(
        "moldagens/<int:pk>/excluir/",
        views.excluir_moldagem,
        name="lab_excluir_moldagem",
    ),
    path("buscar-pacientes/", views.buscar_pacientes, name="lab_buscar_pacientes"),
    path("buscar-alunos-lab/", views.buscar_alunos_lab, name="lab_buscar_alunos_lab"),
    path(
        "selecionar/<str:tipo>/",
        views.materializar,
        name="lab_materializar",
    ),
    path(
        "sincronizar-turma-aluno-busca/",
        views.sincronizar_turma_aluno_busca,
        name="lab_sincronizar_turma_aluno_busca",
    ),
    path("sincronizar/", views.sincronizar_dental, name="lab_sincronizar"),
    path(
        "sincronizar-alunos/",
        views.sincronizar_alunos_eduq,
        name="lab_sincronizar_alunos",
    ),
    # Sincronização agendada — autenticada por token (Railway Cron)
    path(
        "sincronizar-agendado/",
        views.sincronizar_agendado,
        name="lab_sincronizar_agendado",
    ),
]
