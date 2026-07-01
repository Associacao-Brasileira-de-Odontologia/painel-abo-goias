from django.urls import path

from . import views

urlpatterns = [
    path("", views.contratos, name="contratos"),
    path(
        "paciente/<int:paciente_pk>/gerar/",
        views.gerar_contrato_view,
        name="contrato_gerar",
    ),
    path(
        "importar/<str:id_dental>/",
        views.importar_e_gerar,
        name="contrato_importar",
    ),
    path(
        "contrato/<int:contrato_pk>/enviar-dental/",
        views.enviar_ao_dental_view,
        name="contrato_enviar_dental",
    ),
]
