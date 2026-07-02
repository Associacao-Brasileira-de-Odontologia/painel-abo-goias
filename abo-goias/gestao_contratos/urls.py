from django.urls import path

from . import views

urlpatterns = [
    path("", views.contratos, name="contratos"),
    path(
        "paciente/<int:paciente_pk>/confirmar-dados/",
        views.confirmar_dados_view,
        name="contrato_confirmar_dados",
    ),
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
    path(
        "contrato/<int:contrato_pk>/pos-geracao/",
        views.pos_geracao_view,
        name="contrato_pos_geracao",
    ),
    path(
        "contrato/<int:contrato_pk>/baixar/",
        views.baixar_contrato_view,
        name="contrato_baixar",
    ),
    path(
        "contrato/<int:contrato_pk>/baixar-pdf/",
        views.baixar_contrato_pdf_view,
        name="contrato_baixar_pdf",
    ),
    path(
        "contrato/<int:contrato_pk>/enviar-email/",
        views.enviar_email_view,
        name="contrato_enviar_email",
    ),
    path(
        "contrato/<int:contrato_pk>/whatsapp-status/",
        views.whatsapp_status_view,
        name="contrato_whatsapp_status",
    ),
]
