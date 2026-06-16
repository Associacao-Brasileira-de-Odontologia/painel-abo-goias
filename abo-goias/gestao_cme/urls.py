from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='gestao_cme/auth/login.html',
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),
    path(
        'senha/resetar/',
        auth_views.PasswordResetView.as_view(
            template_name='gestao_cme/auth/password_reset_form.html',
            email_template_name='gestao_cme/auth/password_reset_email.html',
            subject_template_name='gestao_cme/auth/password_reset_subject.txt',
            success_url='/senha/resetar/enviado/',
        ),
        name='password_reset',
    ),
    path(
        'senha/resetar/enviado/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='gestao_cme/auth/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'senha/resetar/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='gestao_cme/auth/password_reset_confirm.html',
            success_url='/senha/resetar/concluido/',
        ),
        name='password_reset_confirm',
    ),
    path(
        'senha/resetar/concluido/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='gestao_cme/auth/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path(
        'catalog/',
        RedirectView.as_view(pattern_name='home', permanent=False),
        name='catalog_redirect',
    ),
    path('healthz/', views.healthcheck, name='healthcheck'),
    path('', views.portal, name='home'),
    path('gestao-cme/', views.home, name='cme_home'),
    path('alunos-por-turma/', views.alunos_por_turma, name='alunos_por_turma'),
    path(
        'alunos-por-turma/sincronizar-turmas/',
        views.sincronizar_turmas_eduq,
        name='sincronizar_turmas_eduq',
    ),
    path('abrigos/', views.armarios, name='abrigos'),
    path('armarios/', views.armarios, name='armarios'),
    path('materiais/', views.materiais, name='materiais'),
    path('kits/', views.kits, name='kits'),
]
