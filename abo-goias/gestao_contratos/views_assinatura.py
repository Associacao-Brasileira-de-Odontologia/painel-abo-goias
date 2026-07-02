"""Views do fluxo de assinatura remota.

Views públicas (sem login — o paciente acessa pelo QR Code no próprio
dispositivo) são protegidas por token assinado criptograficamente e
rate-limit por IP. Views de staff gerenciam sessões e exibem o QR Code.
"""

from __future__ import annotations

import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import ContratoGerado
from .services.assinatura import (
    AssinaturaInvalida,
    SessaoInvalida,
    cancelar_sessoes_ativas,
    criar_sessao,
    gerar_token,
    processar_assinatura,
    registrar_abertura,
    resolver_token,
    sessao_ativa,
)

_RATE_LIMIT_REQUISICOES = 30
_RATE_LIMIT_JANELA_SEGUNDOS = 60


def _ip_do_request(request: HttpRequest) -> str | None:
    """Extrai o IP real considerando o proxy do Railway (X-Forwarded-For)."""

    encadeado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encadeado:
        return encadeado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _excedeu_rate_limit(request: HttpRequest, escopo: str) -> bool:
    """Rate-limit simples por IP usando o cache do Django."""

    ip = _ip_do_request(request) or "desconhecido"
    chave = f"assinatura_rl_{escopo}_{ip}"
    atual = cache.get_or_set(chave, 0, _RATE_LIMIT_JANELA_SEGUNDOS)
    if atual >= _RATE_LIMIT_REQUISICOES:
        return True
    try:
        cache.incr(chave)
    except ValueError:
        cache.set(chave, 1, _RATE_LIMIT_JANELA_SEGUNDOS)
    return False


# ── Views públicas (paciente) ─────────────────────────────────────────────────


def assinar_view(request: HttpRequest, token: str) -> HttpResponse:
    """Página pública de assinatura acessada via QR Code.

    GET: exibe o contrato e a área de assinatura (canvas).
    POST: recebe o PNG do canvas e conclui a assinatura.
    """

    if _excedeu_rate_limit(request, "assinar"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    try:
        sessao = resolver_token(token)
    except SessaoInvalida as exc:
        return render(
            request,
            "gestao_contratos/assinatura_invalida.html",
            {"motivo": exc.motivo},
            status=410,
        )

    contrato = sessao.contrato
    paciente = contrato.paciente

    if request.method == "POST":
        try:
            processar_assinatura(
                sessao,
                request.POST.get("assinatura", ""),
                ip=_ip_do_request(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except AssinaturaInvalida as exc:
            return render(
                request,
                "gestao_contratos/assinar.html",
                {
                    "sessao": sessao,
                    "contrato": contrato,
                    "paciente": paciente,
                    "token": token,
                    "erro": str(exc),
                },
            )
        except SessaoInvalida as exc:
            return render(
                request,
                "gestao_contratos/assinatura_invalida.html",
                {"motivo": exc.motivo},
                status=410,
            )
        return render(
            request,
            "gestao_contratos/assinatura_concluida.html",
            {"contrato": contrato, "paciente": paciente},
        )

    registrar_abertura(sessao)
    return render(
        request,
        "gestao_contratos/assinar.html",
        {
            "sessao": sessao,
            "contrato": contrato,
            "paciente": paciente,
            "token": token,
        },
    )


def assinar_pdf_view(request: HttpRequest, token: str) -> HttpResponse:
    """Serve o PDF do contrato para visualização na página pública."""

    if _excedeu_rate_limit(request, "pdf"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    try:
        sessao = resolver_token(token)
    except SessaoInvalida:
        raise Http404

    from .services.assinatura import _obter_pdf_original

    conteudo = _obter_pdf_original(sessao.contrato)
    response = HttpResponse(conteudo, content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="contrato.pdf"'
    return response


# ── Views de staff ────────────────────────────────────────────────────────────


@login_required
def iniciar_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Cria (ou renova) a sessão de assinatura e volta à pós-geração."""

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)

    if contrato.status == "assinado":
        messages.info(request, "Este contrato já foi assinado.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    criar_sessao(contrato, criado_por=request.user)
    messages.success(
        request,
        "Sessão de assinatura criada. Peça ao paciente para escanear o QR Code.",
    )
    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def cancelar_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Cancela a sessão de assinatura ativa do contrato."""

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    canceladas = cancelar_sessoes_ativas(contrato)

    if canceladas and contrato.status == "aguardando_assinatura":
        contrato.status = "gerado"
        contrato.save(update_fields=["status", "atualizado_em"])

    messages.info(
        request,
        (
            "Sessão de assinatura cancelada."
            if canceladas
            else "Nenhuma sessão ativa para cancelar."
        ),
    )
    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def qr_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Retorna o PNG do QR Code apontando para a URL pública de assinatura."""

    import qrcode

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    sessao = sessao_ativa(contrato)
    if sessao is None:
        raise Http404("Nenhuma sessão de assinatura ativa.")

    url = request.build_absolute_uri(
        reverse("assinatura_publica", args=[gerar_token(sessao)])
    )
    imagem = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    imagem.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@login_required
def baixar_contrato_assinado_view(
    request: HttpRequest, contrato_pk: int
) -> HttpResponse:
    """Retorna o PDF assinado do contrato como download."""

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    if not contrato.arquivo_pdf_assinado:
        messages.error(request, "Este contrato ainda não possui versão assinada.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato.arquivo_pdf_assinado.open("rb")
    conteudo = contrato.arquivo_pdf_assinado.read()
    contrato.arquivo_pdf_assinado.close()

    nome_arquivo = (
        f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
        f"_{paciente.id_dental}_assinado.pdf"
    )
    response = HttpResponse(conteudo, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
