"""Cliente HTTP para a Meta WhatsApp Business Cloud API.

Usa urllib da biblioteca padrão (sem dependências externas), no mesmo
estilo do cliente Dental Office (gestao_lab/integrations/dental.py).

Nota sobre templates de mensagem: o WhatsApp Business exige que
conversas iniciadas pela empresa (fora de uma janela de atendimento de
24h aberta pelo próprio paciente) usem uma mensagem de "template"
pré-aprovada pela Meta. Por isso, quando WHATSAPP_META_TEMPLATE_NAME
está configurado, o envio usa o modo de template — presumindo um
template com um cabeçalho do tipo DOCUMENT e uma variável de corpo
(o nome do paciente). Sem template configurado, tenta uma mensagem de
documento "de sessão", que só é aceita pela Meta se o paciente tiver
escrito para o número da clínica nas últimas 24h.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_MENSAGEM_SESSAO = (
    "Olá! Seu contrato foi assinado com sucesso. Segue uma cópia em PDF. "
    "Obrigado — ABO Goiás."
)


class MetaWhatsAppError(Exception):
    """Erro de comunicação ou resposta inesperada da Meta Cloud API."""


@dataclass(frozen=True)
class ConfigMetaWhatsapp:
    """Configuração necessária para autenticar e enviar mensagens."""

    token: str
    phone_number_id: str
    api_version: str
    template_name: str
    template_lang: str
    timeout: int


def carregar_config_meta() -> ConfigMetaWhatsapp | None:
    """Carrega a configuração da Meta Cloud API a partir do ambiente.

    Retorna None se as credenciais obrigatórias (token e phone_number_id)
    não estiverem presentes — o chamador deve tratar isso como "envio
    automático desativado", não como um erro.
    """

    token = os.environ.get("WHATSAPP_META_TOKEN", "").strip()
    phone_number_id = os.environ.get("WHATSAPP_META_PHONE_NUMBER_ID", "").strip()
    if not token or not phone_number_id:
        return None

    return ConfigMetaWhatsapp(
        token=token,
        phone_number_id=phone_number_id,
        api_version=os.environ.get("WHATSAPP_META_API_VERSION", "v21.0").strip(),
        template_name=os.environ.get("WHATSAPP_META_TEMPLATE_NAME", "").strip(),
        template_lang=os.environ.get("WHATSAPP_META_TEMPLATE_LANG", "pt_BR").strip(),
        timeout=int(os.environ.get("WHATSAPP_META_TIMEOUT", "30")),
    )


class MetaWhatsAppClient:
    """Cliente para enviar documentos via Meta WhatsApp Business Cloud API.

    O envio de um documento é feito em duas etapas: upload da mídia
    (POST .../media) para obter um ID, e envio da mensagem referenciando
    esse ID (POST .../messages).
    """

    def __init__(self, config: ConfigMetaWhatsapp | None = None) -> None:
        self.config = config or carregar_config_meta()
        if self.config is None:
            raise MetaWhatsAppError(
                "Configure WHATSAPP_META_TOKEN e WHATSAPP_META_PHONE_NUMBER_ID."
            )

    def enviar_documento(
        self,
        destinatario: str,
        arquivo_bytes: bytes,
        nome_arquivo: str,
        nome_paciente: str,
    ) -> str:
        """Envia um PDF ao destinatário e retorna o ID externo da mensagem.

        ``destinatario`` deve estar no formato aceito pela Meta: DDI + DDD +
        número, apenas dígitos (ex.: "5562999998888"). Raises
        MetaWhatsAppError em qualquer falha de upload, envio ou resposta
        inesperada da API.
        """

        media_id = self._upload_media(arquivo_bytes, nome_arquivo)

        if self.config.template_name:
            payload = self._payload_template(
                destinatario, media_id, nome_arquivo, nome_paciente
            )
        else:
            payload = self._payload_documento_sessao(
                destinatario, media_id, nome_arquivo
            )

        return self._enviar_mensagem(payload)

    # ── Construção dos payloads ─────────────────────────────────────────

    def _payload_template(
        self, destinatario: str, media_id: str, nome_arquivo: str, nome_paciente: str
    ) -> dict[str, Any]:
        return {
            "messaging_product": "whatsapp",
            "to": destinatario,
            "type": "template",
            "template": {
                "name": self.config.template_name,
                "language": {"code": self.config.template_lang},
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type": "document",
                                "document": {
                                    "id": media_id,
                                    "filename": nome_arquivo,
                                },
                            }
                        ],
                    },
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": nome_paciente}],
                    },
                ],
            },
        }

    def _payload_documento_sessao(
        self, destinatario: str, media_id: str, nome_arquivo: str
    ) -> dict[str, Any]:
        return {
            "messaging_product": "whatsapp",
            "to": destinatario,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": nome_arquivo,
                "caption": _MENSAGEM_SESSAO,
            },
        }

    # ── Chamadas HTTP ─────────────────────────────────────────────────────

    def _upload_media(self, arquivo_bytes: bytes, nome_arquivo: str) -> str:
        url = (
            f"https://graph.facebook.com/{self.config.api_version}/"
            f"{self.config.phone_number_id}/media"
        )
        campos = {"messaging_product": "whatsapp", "type": "application/pdf"}
        arquivos = {"file": (nome_arquivo, "application/pdf", arquivo_bytes)}
        resposta = self._post_multipart(url, campos, arquivos)
        media_id = resposta.get("id")
        if not media_id:
            raise MetaWhatsAppError(f"Upload de mídia não retornou 'id': {resposta}")
        return media_id

    def _enviar_mensagem(self, payload: dict[str, Any]) -> str:
        url = (
            f"https://graph.facebook.com/{self.config.api_version}/"
            f"{self.config.phone_number_id}/messages"
        )
        resposta = self._post_json(url, payload)
        mensagens = resposta.get("messages") or []
        if not mensagens:
            raise MetaWhatsAppError(f"Resposta sem 'messages': {resposta}")
        return mensagens[0].get("id", "")

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._executar(request)

    def _post_multipart(
        self,
        url: str,
        campos: dict[str, str],
        arquivos: dict[str, tuple[str, str, bytes]],
    ) -> dict[str, Any]:
        boundary = ("----WhatsAppBoundary" + uuid.uuid4().hex).encode("ascii")

        body = b""
        for nome, valor in campos.items():
            body += b"--" + boundary + b"\r\n"
            body += f'Content-Disposition: form-data; name="{nome}"\r\n\r\n'.encode(
                "utf-8"
            )
            body += valor.encode("utf-8") + b"\r\n"
        for nome, (filename, content_type, dados) in arquivos.items():
            body += b"--" + boundary + b"\r\n"
            body += (
                f'Content-Disposition: form-data; name="{nome}";'
                f' filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            body += dados + b"\r\n"
        body += b"--" + boundary + b"--\r\n"

        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary.decode('ascii')}",
        }
        request = Request(url, data=body, headers=headers, method="POST")
        return self._executar(request)

    def _executar(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.config.timeout) as response:
                corpo = response.read().decode("utf-8")
        except HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")
            raise MetaWhatsAppError(
                f"Erro HTTP {exc.code} na Meta Cloud API: {detalhe}"
            ) from exc
        except URLError as exc:
            raise MetaWhatsAppError(
                f"Falha de conexão com a Meta Cloud API: {exc.reason}"
            ) from exc

        if not corpo.strip():
            return {}
        try:
            return json.loads(corpo)
        except json.JSONDecodeError as exc:
            trecho = corpo[:200].replace("\n", " ")
            raise MetaWhatsAppError(
                f"Resposta não-JSON da Meta Cloud API: {trecho!r}"
            ) from exc
