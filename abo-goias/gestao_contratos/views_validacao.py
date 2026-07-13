"""Página pública de validação de documentos assinados.

Qualquer pessoa que possua um PDF assinado pelo sistema pode conferir sua
autenticidade e integridade aqui, enviando o arquivo — o SHA-256 é
recalculado e comparado ao que o sistema registrou. Não exige login (quem
valida já tem o documento em mãos) e é protegida por rate-limit por IP,
como as demais páginas públicas do fluxo de assinatura.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .services.validacao import MAX_UPLOAD_BYTES, ArquivoInvalido, validar_pdf
from .views_assinatura import _excedeu_rate_limit

_TEMPLATE = "gestao_contratos/validar.html"


def validar_documento_view(request: HttpRequest) -> HttpResponse:
    """Exibe o formulário de validação e processa o PDF enviado.

    GET: mostra a área de upload.
    POST: confere o arquivo e renderiza o selo (autêntico / não confere) ou
    uma mensagem de erro para uploads inválidos.
    """

    if request.method != "POST":
        return render(request, _TEMPLATE, {})

    if _excedeu_rate_limit(request, "validar"):
        return render(
            request,
            _TEMPLATE,
            {"erro": "Muitas tentativas. Aguarde um instante e tente novamente."},
            status=429,
        )

    arquivo = request.FILES.get("documento")
    try:
        conteudo = _ler_upload(arquivo)
        resultado = validar_pdf(conteudo)
    except ArquivoInvalido as exc:
        return render(request, _TEMPLATE, {"erro": str(exc)})

    return render(request, _TEMPLATE, {"resultado": resultado})


def _ler_upload(arquivo) -> bytes:
    """Valida o tamanho antes de ler o upload inteiro para a memória."""

    if arquivo is None:
        raise ArquivoInvalido("Selecione um arquivo PDF para validar.")
    if arquivo.size and arquivo.size > MAX_UPLOAD_BYTES:
        raise ArquivoInvalido("Arquivo muito grande (máximo de 20 MB).")
    return arquivo.read()
