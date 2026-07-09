"""Serialização dos payloads enviados à Z-API.

Mantém o formato específico do provedor isolado deste módulo — trocar de
provedor no futuro significa escrever um novo ``serializers``-equivalente
para o novo módulo do provedor, sem tocar em ``MessagingService`` nem no
restante da aplicação.
"""

from __future__ import annotations

import base64
from typing import Any


def payload_texto(destinatario: str, mensagem: str) -> dict[str, Any]:
    """Monta o payload de envio de texto simples da Z-API."""

    return {"phone": destinatario, "message": mensagem}


def _data_uri(arquivo_bytes: bytes, content_type: str) -> str:
    codificado = base64.b64encode(arquivo_bytes).decode("ascii")
    return f"data:{content_type};base64,{codificado}"


def payload_documento(
    destinatario: str,
    arquivo_bytes: bytes,
    nome_arquivo: str,
    legenda: str,
    content_type: str = "application/pdf",
) -> dict[str, Any]:
    """Monta o payload de envio de documento da Z-API (arquivo em base64)."""

    payload: dict[str, Any] = {
        "phone": destinatario,
        "document": _data_uri(arquivo_bytes, content_type),
        "fileName": nome_arquivo,
    }
    if legenda:
        payload["caption"] = legenda
    return payload


def payload_imagem(
    destinatario: str,
    arquivo_bytes: bytes,
    legenda: str,
    content_type: str = "image/png",
) -> dict[str, Any]:
    """Monta o payload de envio de imagem da Z-API (arquivo em base64)."""

    payload: dict[str, Any] = {
        "phone": destinatario,
        "image": _data_uri(arquivo_bytes, content_type),
    }
    if legenda:
        payload["caption"] = legenda
    return payload
