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
    # Alunos (Dental Office)
    path("alunos/", views.alunos_lab, name="lab_alunos"),
    # Pacientes (Dental Office)
    path("pacientes/", views.pacientes, name="lab_pacientes"),
    # Sincronização Dental Office
    path("sincronizar/", views.sincronizar_dental, name="lab_sincronizar"),
]
