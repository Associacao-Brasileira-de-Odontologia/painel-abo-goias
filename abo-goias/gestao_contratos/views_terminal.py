"""Views do terminal de assinatura dedicado (ex.: tablet da recepção).

Público, sem login — o tablet fica com o navegador aberto indefinidamente
nesta URL. Enquanto não há sessão de assinatura enviada para o terminal,
mostra uma tela de espera que faz polling (HTMX); assim que o colaborador
envia um contrato para este terminal (ver iniciar_assinatura_view), o
polling detecta a sessão e redireciona automaticamente para a mesma tela
pública de assinatura usada no fluxo por QR Code — sem nenhum código
duplicado, e sem o paciente (ou colaborador) precisar tocar em nada além
do próprio tablet.
"""

from __future__ import annotations

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import TerminalAssinatura
from .services.assinatura import gerar_token, sessao_ativa_para_terminal
from .views_assinatura import _excedeu_rate_limit


def _resolver_terminal(token: str) -> TerminalAssinatura:
    """Busca o terminal pelo token e expira sob demanda se estiver ativo
    há mais de TERMINAL_ATIVO_TTL_HORAS — mesmo padrão de lazy-expire já
    usado para sessões de assinatura (ver services/assinatura.py)."""

    terminal = get_object_or_404(TerminalAssinatura, token=token)
    terminal.expirar_se_vencido()
    if not terminal.ativo:
        raise Http404
    return terminal


def terminal_assinatura_view(request: HttpRequest, token: str) -> HttpResponse:
    """Tela principal do terminal — redireciona para a assinatura quando
    houver uma sessão enviada a ele, ou mostra a tela de espera."""

    if _excedeu_rate_limit(request, "terminal"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    terminal = _resolver_terminal(token)

    sessao = sessao_ativa_para_terminal(terminal)
    if sessao is not None:
        return redirect("assinatura_publica", token=gerar_token(sessao))

    return render(
        request,
        "gestao_contratos/terminal_aguardando.html",
        {"terminal": terminal},
    )


def terminal_status_fragment_view(request: HttpRequest, token: str) -> HttpResponse:
    """Alvo do polling HTMX da tela de espera.

    Enquanto não há sessão, apenas reenvia o mesmo fragmento de espera
    (o polling continua). Assim que uma sessão é encontrada, responde com
    o cabeçalho HX-Redirect — o HTMX então força o navegador do tablet a
    navegar de verdade para a tela de assinatura, sem precisar de nenhum
    toque do paciente ou do colaborador.
    """

    if _excedeu_rate_limit(request, "terminal"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    terminal = _resolver_terminal(token)

    sessao = sessao_ativa_para_terminal(terminal)
    if sessao is not None:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse(
            "assinatura_publica", args=[gerar_token(sessao)]
        )
        return response

    return render(
        request,
        "gestao_contratos/_terminal_aguardando_fragment.html",
        {"terminal": terminal},
    )
