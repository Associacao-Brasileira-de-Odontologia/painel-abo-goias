from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('catalog/', views.home, name='catalog_home'),
]
