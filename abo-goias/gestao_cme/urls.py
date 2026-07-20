from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path(
        "catalog/",
        RedirectView.as_view(pattern_name="home", permanent=False),
        name="catalog_redirect",
    ),
    path("healthz/", views.healthcheck, name="healthcheck"),
    path("", views.portal, name="home"),
    path(
        "gestao-cme/",
        RedirectView.as_view(pattern_name="cme_dashboard", permanent=False),
        name="cme_entrada",
    ),
    path("gestao-cme/movimentacoes/", views.home, name="cme_home"),
    path("gestao-cme/visao-geral/", views.cme_dashboard, name="cme_dashboard"),
    path("alunos-por-turma/", views.alunos_por_turma, name="alunos_por_turma"),
    path(
        "alunos-por-turma/sincronizar-turmas/",
        views.sincronizar_turmas_eduq,
        name="sincronizar_turmas_eduq",
    ),
    path("abrigos/", views.armarios, name="abrigos"),
    path("abrigos/novo/", views.cadastrar_abrigo, name="cadastrar_abrigo"),
    path("abrigos/<int:pk>/editar/", views.editar_abrigo, name="editar_abrigo"),
    path("abrigos/<int:pk>/excluir/", views.excluir_abrigo, name="excluir_abrigo"),
    path("materiais/", views.materiais, name="materiais"),
    path("materiais/novo/", views.cadastrar_material, name="cadastrar_material"),
    path("materiais/<int:pk>/editar/", views.editar_material, name="editar_material"),
    path(
        "materiais/<int:pk>/excluir/", views.excluir_material, name="excluir_material"
    ),
    path("kits/", views.kits, name="kits"),
    path("kits/novo/", views.cadastrar_kit, name="cadastrar_kit"),
    path("kits/<int:pk>/editar/", views.editar_kit, name="editar_kit"),
    path("kits/<int:pk>/excluir/", views.excluir_kit, name="excluir_kit"),
    path("alunos/buscar/", views.buscar_alunos, name="buscar_alunos"),
    path(
        "alunos/sincronizar-turma-busca/",
        views.sincronizar_turma_busca,
        name="sincronizar_turma_busca",
    ),
    path(
        "alunos/atualizar/", views.atualizar_alunos_eduq, name="atualizar_alunos_eduq"
    ),
    path("gestao-cme/nova-saida/", views.registrar_saida, name="registrar_saida"),
    path("gestao-cme/nova-entrada/", views.registrar_entrada, name="registrar_entrada"),
    path(
        "gestao-cme/<int:pk>/alternar-retirado/",
        views.alternar_retirado,
        name="alternar_retirado",
    ),
    path(
        "gestao-cme/<int:pk>/excluir/",
        views.excluir_movimentacao,
        name="excluir_movimentacao",
    ),
    path(
        "gestao-cme/<int:pk>/editar/",
        views.editar_movimentacao,
        name="editar_movimentacao",
    ),
    path(
        "alunos-por-turma/sincronizar-alunos/<int:turma_id>/",
        views.sincronizar_alunos_turma,
        name="sincronizar_alunos_turma",
    ),
    path("alunos-por-turma/novo/", views.cadastrar_aluno, name="cadastrar_aluno"),
    path(
        "alunos-por-turma/<int:aluno_id>/abrigo/",
        views.atribuir_abrigo,
        name="atribuir_abrigo",
    ),
    path("turmas/nova/", views.cadastrar_turma, name="cadastrar_turma"),
    path("emprestimos/", views.emprestimos, name="emprestimos"),
    path("emprestimos/novo/", views.criar_emprestimo, name="criar_emprestimo"),
    path(
        "emprestimos/<int:pk>/editar/",
        views.editar_emprestimo,
        name="editar_emprestimo",
    ),
    path(
        "emprestimos/<int:pk>/devolver/",
        views.devolver_emprestimo,
        name="devolver_emprestimo",
    ),
    path(
        "emprestimos/<int:pk>/marcar-atrasado/",
        views.marcar_emprestimo_atrasado,
        name="marcar_emprestimo_atrasado",
    ),
]
