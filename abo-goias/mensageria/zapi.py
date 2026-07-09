"""Implementação concreta do MessagingProvider para a Z-API.

Referência: https://developer.z-api.io — API não-oficial de envio de
WhatsApp via sessão QR Code (instância). Toda a especificidade do
protocolo HTTP da Z-API (URLs, payloads, cabeçalhos, códigos de erro) fica
confinada a este módulo — nenhum outro arquivo do projeto conhece o
formato de requisição/resposta da Z-API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from . import serializers
from .exceptions import (
    InstanceDisconnectedError,
    MessageRejectedError,
    MessagingAuthenticationError,
    MessagingConfigurationError,
    MessagingError,
    MessagingTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
from .provider import MessagingProvider
from .responses import DisponibilidadeResult, MessagingResult
from .utils import log_envio
from .validators import validar_destinatario


@dataclass(frozen=True)
class ConfigZApi:
    """Configuração necessária para autenticar e enviar mensagens pela Z-API."""

    instance_id: str
    token: str
    client_token: str
    base_url: str
    timeout: int


def carregar_config_zapi() -> ConfigZApi | None:
    """Carrega a configuração da Z-API a partir de settings.

    Retorna ``None`` se as credenciais obrigatórias (instance id e token)
    não estiverem presentes — o chamador deve tratar isso como "envio
    automático desativado", não como um erro.
    """

    instance_id = (settings.ZAPI_INSTANCE_ID or "").strip()
    token = (settings.ZAPI_TOKEN or "").strip()
    if not instance_id or not token:
        return None

    return ConfigZApi(
        instance_id=instance_id,
        token=token,
        client_token=(settings.ZAPI_CLIENT_TOKEN or "").strip(),
        base_url=(settings.ZAPI_BASE_URL or "https://api.z-api.io").rstrip("/"),
        timeout=int(settings.ZAPI_TIMEOUT or 30),
    )


class ZApiProvider(MessagingProvider):
    """Cliente HTTP da Z-API — implementa o contrato ``MessagingProvider``."""

    def __init__(self, config: ConfigZApi | None = None) -> None:
        self.config = config or carregar_config_zapi()
        if self.config is None:
            raise MessagingConfigurationError(
                "Configure ZAPI_INSTANCE_ID e ZAPI_TOKEN."
            )

    # ── Contrato MessagingProvider ───────────────────────────────────────

    def enviar_texto(self, destinatario: str, mensagem: str) -> MessagingResult:
        destinatario = validar_destinatario(destinatario)
        payload = serializers.payload_texto(destinatario, mensagem)
        return self._enviar("send-text", "texto", destinatario, payload)

    def enviar_documento(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        legenda: str = "",
    ) -> MessagingResult:
        destinatario = validar_destinatario(destinatario)
        extensao = (
            nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else "pdf"
        )
        payload = serializers.payload_documento(
            destinatario, arquivo_bytes, nome_arquivo, legenda
        )
        return self._enviar(
            f"send-document/{extensao}", "documento", destinatario, payload
        )

    def enviar_imagem(
        self, destinatario: str, arquivo_bytes: bytes, legenda: str = ""
    ) -> MessagingResult:
        destinatario = validar_destinatario(destinatario)
        payload = serializers.payload_imagem(destinatario, arquivo_bytes, legenda)
        return self._enviar("send-image", "imagem", destinatario, payload)

    def enviar_arquivo(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        content_type: str,
        legenda: str = "",
    ) -> MessagingResult:
        if content_type.startswith("image/"):
            return self.enviar_imagem(destinatario, arquivo_bytes, legenda)
        return self.enviar_documento(destinatario, arquivo_bytes, nome_arquivo, legenda)

    def verificar_disponibilidade(self) -> DisponibilidadeResult:
        try:
            resposta = self._request("GET", "status", None, tipo_mensagem="status")
        except MessagingError as exc:
            return DisponibilidadeResult(disponivel=False, detalhe=str(exc))

        conectado = bool(
            resposta.get("connected") or resposta.get("smartphoneConnected")
        )
        detalhe = "" if conectado else "Instância sem sessão ativa (aguardando QR Code)."
        return DisponibilidadeResult(disponivel=conectado, detalhe=detalhe)

    # ── Envio + tradução de resposta ─────────────────────────────────────

    def _enviar(
        self,
        endpoint: str,
        tipo_mensagem: str,
        destinatario: str,
        payload: dict[str, Any],
    ) -> MessagingResult:
        resposta = self._request(
            "POST",
            endpoint,
            payload,
            tipo_mensagem=tipo_mensagem,
            destinatario=destinatario,
        )

        erro_api = resposta.get("error")
        if erro_api:
            raise MessageRejectedError(f"Z-API recusou a mensagem: {erro_api}")

        message_id = (
            resposta.get("messageId") or resposta.get("zaapId") or resposta.get("id") or ""
        )
        if not message_id:
            raise MessagingError(
                f"Resposta da Z-API sem identificador de mensagem: {resposta}"
            )

        return MessagingResult.ok(message_id, resposta=resposta)

    # ── HTTP ──────────────────────────────────────────────────────────────

    def _url(self, endpoint: str) -> str:
        return (
            f"{self.config.base_url}/instances/{self.config.instance_id}"
            f"/token/{self.config.token}/{endpoint}"
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None,
        *,
        tipo_mensagem: str,
        destinatario: str = "",
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.client_token:
            headers["Client-Token"] = self.config.client_token

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self._url(endpoint), data=data, headers=headers, method=method)

        inicio = time.monotonic()
        try:
            with urlopen(request, timeout=self.config.timeout) as response:
                status_http = response.status
                corpo = response.read().decode("utf-8")
        except HTTPError as exc:
            status_http = exc.code
            corpo = exc.read().decode("utf-8", errors="replace")
            self._log(endpoint, destinatario, tipo_mensagem, status_http, inicio, False, corpo)
            raise self._erro_para_status(status_http, corpo) from exc
        except TimeoutError as exc:
            self._log(endpoint, destinatario, tipo_mensagem, None, inicio, False, "timeout")
            raise MessagingTimeoutError(f"Timeout ao comunicar com a Z-API: {exc}") from exc
        except URLError as exc:
            self._log(
                endpoint, destinatario, tipo_mensagem, None, inicio, False, str(exc.reason)
            )
            if isinstance(exc.reason, TimeoutError):
                raise MessagingTimeoutError(
                    f"Timeout ao comunicar com a Z-API: {exc.reason}"
                ) from exc
            raise ProviderUnavailableError(
                f"Falha de conexão com a Z-API: {exc.reason}"
            ) from exc

        resultado = self._decodificar(corpo)
        self._log(endpoint, destinatario, tipo_mensagem, status_http, inicio, True, "ok")
        return resultado

    def _decodificar(self, corpo: str) -> dict[str, Any]:
        if not corpo.strip():
            return {}
        try:
            return json.loads(corpo)
        except json.JSONDecodeError as exc:
            trecho = corpo[:200].replace("\n", " ")
            raise MessagingError(f"Resposta não-JSON da Z-API: {trecho!r}") from exc

    def _erro_para_status(self, status_http: int, corpo: str) -> MessagingError:
        if status_http in (401, 403):
            return MessagingAuthenticationError(
                f"Autenticação recusada pela Z-API (HTTP {status_http}): {corpo}"
            )
        if status_http == 404:
            return InstanceDisconnectedError(
                f"Instância Z-API não encontrada ou desconectada (HTTP 404): {corpo}"
            )
        if status_http == 429:
            return RateLimitExceededError(
                f"Limite de requisições da Z-API excedido (HTTP 429): {corpo}"
            )
        if 500 <= status_http < 600:
            return ProviderUnavailableError(
                f"Erro interno da Z-API (HTTP {status_http}): {corpo}"
            )
        return MessagingError(f"Erro HTTP {status_http} na Z-API: {corpo}")

    def _log(
        self,
        endpoint: str,
        destinatario: str,
        tipo_mensagem: str,
        status_http: int | None,
        inicio: float,
        sucesso: bool,
        resultado: str,
    ) -> None:
        log_envio(
            endpoint=endpoint,
            destinatario=destinatario,
            tipo_mensagem=tipo_mensagem,
            status_http=status_http,
            duracao_segundos=time.monotonic() - inicio,
            sucesso=sucesso,
            resultado=resultado,
        )
