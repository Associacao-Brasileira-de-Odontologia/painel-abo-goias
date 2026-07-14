from django.urls import path

from . import views

app_name = "identificadores"

urlpatterns = [
    path("", views.index, name="index"),
    path("turmas/buscar/", views.buscar_turmas, name="buscar_turmas"),
    path("turmas/<int:turma_id>/alunos/", views.turma_alunos, name="turma_alunos"),
    path("sincronizar/", views.sincronizar, name="sincronizar"),
    path("baixar/<str:nome_arquivo>/", views.baixar, name="baixar"),
]
