from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import SolicitacaoCadastroForm


@login_required
def perfil(request: HttpRequest) -> HttpResponse:
    """Exibe os dados da conta do usuário autenticado."""

    return render(request, "auth/perfil.html")


def solicitar_acesso(request: HttpRequest) -> HttpResponse:
    """Tela pública para solicitar acesso ao sistema.

    Cria uma :class:`~contas.models.SolicitacaoCadastro` pendente — o
    cadastro nunca é imediato: um administrador revisa e aprova (ou
    rejeita) o pedido pelo Django Admin. Quem já está autenticado é
    redirecionado ao portal.
    """

    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = SolicitacaoCadastroForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("solicitar_acesso_enviado")
    else:
        form = SolicitacaoCadastroForm()

    return render(request, "auth/solicitar_acesso.html", {"form": form})


def solicitar_acesso_enviado(request: HttpRequest) -> HttpResponse:
    """Confirmação exibida após enviar uma solicitação de acesso."""

    return render(request, "auth/solicitar_acesso_enviado.html")
