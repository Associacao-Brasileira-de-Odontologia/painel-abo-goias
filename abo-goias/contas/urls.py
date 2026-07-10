from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="auth/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "senha/resetar/",
        auth_views.PasswordResetView.as_view(
            template_name="auth/password_reset_form.html",
            email_template_name="auth/password_reset_email.html",
            subject_template_name="auth/password_reset_subject.txt",
            success_url="/senha/resetar/enviado/",
        ),
        name="password_reset",
    ),
    path(
        "senha/resetar/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="auth/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "senha/resetar/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="auth/password_reset_confirm.html",
            success_url="/senha/resetar/concluido/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "senha/resetar/concluido/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="auth/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("solicitar-acesso/", views.solicitar_acesso, name="solicitar_acesso"),
    path(
        "solicitar-acesso/enviado/",
        views.solicitar_acesso_enviado,
        name="solicitar_acesso_enviado",
    ),
    path("perfil/", views.perfil, name="perfil"),
    path(
        "senha/trocar/",
        auth_views.PasswordChangeView.as_view(
            template_name="auth/password_change_form.html",
            success_url="/senha/trocar/concluido/",
        ),
        name="password_change",
    ),
    path(
        "senha/trocar/concluido/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="auth/password_change_done.html",
        ),
        name="password_change_done",
    ),
]
