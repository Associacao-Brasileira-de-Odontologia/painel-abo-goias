"""Formulários da aplicação de contas."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator

from .models import SolicitacaoCadastro


class SolicitacaoCadastroForm(forms.ModelForm):
    """Formulário público de solicitação de acesso ao sistema.

    Valida que o usuário/e-mail desejados ainda não pertencem a uma conta
    existente nem a outra solicitação pendente, evitando duplicidade antes
    mesmo de o administrador revisar.
    """

    username = forms.CharField(
        label="Usuário desejado",
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        help_text="Letras, números e @/./+/-/_ apenas.",
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )

    class Meta:
        model = SolicitacaoCadastro
        fields = ["nome_completo", "email", "username", "cargo", "justificativa"]
        widgets = {
            "nome_completo": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "cargo": forms.TextInput(),
            "justificativa": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "nome_completo": "Nome completo",
            "email": "E-mail",
            "cargo": "Cargo / função",
            "justificativa": "Justificativa",
        }

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "Já existe um usuário com esse nome. Escolha outro."
            )
        if SolicitacaoCadastro.objects.filter(
            username__iexact=username, status=SolicitacaoCadastro.Status.PENDENTE
        ).exists():
            raise forms.ValidationError(
                "Já existe uma solicitação pendente com esse usuário."
            )
        return username

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Já existe uma conta com esse e-mail. Use a opção "
                "'Esqueci minha senha' na tela de login."
            )
        if SolicitacaoCadastro.objects.filter(
            email__iexact=email, status=SolicitacaoCadastro.Status.PENDENTE
        ).exists():
            raise forms.ValidationError(
                "Já existe uma solicitação pendente com esse e-mail."
            )
        return email
