from django.urls import path

from . import views

app_name = "identificadores"

urlpatterns = [
    path("", views.index, name="index"),
    path("baixar/<str:nome_arquivo>/", views.baixar, name="baixar"),
]
