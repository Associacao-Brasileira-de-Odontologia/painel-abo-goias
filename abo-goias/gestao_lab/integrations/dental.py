"""Integracao com a API Dental Office.

Autentica via client_id/secret, armazena o token no cache Django (TTL 23h)
e expoe um cliente HTTP base para os servicos de sincronizacao usarem.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, urlopen

from django.conf import settings
from django.core.cache import cache

# Margem de 1h abaixo do limite real (24h) para evitar uso de token prestes a expirar
_DENTAL_TOKEN_TTL = 23 * 60 * 60


class DentalAPIError(Exception):
    """Erro de configuracao, autenticacao ou comunicacao com a API Dental Office."""

    pass


@dataclass(frozen=True)
class ConfigDental:
    """Configuracao necessaria para autenticar e consultar a API Dental Office."""

    client_id: str
    secret: str
    auth_url: str
    base_url: str
    verify_tls: bool
    timeout: int
    use_proxy: bool


@dataclass(frozen=True)
class PacienteDental:
    """Representacao normalizada de um paciente recebido do Dental Office."""

    id: int
    nome: str
    celular: str
    ativo: bool


@dataclass(frozen=True)
class AlunoLabDental:
    """Representacao normalizada de um aluno (usuario grupo 8) do Dental Office."""

    id: int
    nome: str
    celular: str
    ativo: bool


def _carregar_env() -> None:
    """Carrega variaveis de ambiente de arquivos .env conhecidos do projeto."""

    candidatos = [
        settings.BASE_DIR / ".env",
        settings.BASE_DIR.parent / ".env",
    ]
    for arquivo in candidatos:
        if not Path(arquivo).exists():
            continue
        for linha in Path(arquivo).read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
        break


def carregar_config_dental() -> ConfigDental:
    """Monta a configuracao da API Dental Office a partir do ambiente e settings.

    Valida credenciais obrigatorias e converte opcoes de TLS, timeout e proxy.
    """

    _carregar_env()
    client_id = os.getenv("DENTAL_CLIENT_ID", "").strip()
    secret = os.getenv("DENTAL_SECRET", "").strip()

    ausentes = [
        nome
        for nome, valor in (("CLIENT_ID", client_id), ("SECRET", secret))
        if not valor
    ]
    if ausentes:
        variaveis = ", ".join(f"DENTAL_{nome}" for nome in ausentes)
        raise DentalAPIError(f"Configure as variaveis de ambiente: {variaveis}")

    return ConfigDental(
        client_id=client_id,
        secret=secret,
        auth_url=os.getenv("DENTAL_AUTH_URL", settings.DENTAL_AUTH_URL).strip(),
        base_url=os.getenv("DENTAL_BASE_URL", settings.DENTAL_BASE_URL).strip(),
        verify_tls=_ler_booleano("DENTAL_VERIFY_TLS", settings.DENTAL_VERIFY_TLS),
        timeout=int(os.getenv("DENTAL_TIMEOUT", settings.DENTAL_TIMEOUT)),
        use_proxy=_ler_booleano(
            "DENTAL_USE_PROXY", getattr(settings, "DENTAL_USE_PROXY", False)
        ),
    )


class DentalClient:
    """Cliente HTTP para autenticar e consultar dados no Dental Office.

    O token de acesso e armazenado no cache Django com TTL de 23h para ser
    reutilizado entre instancias e requisicoes. Quando uma requisicao retorna
    HTTP 401 ou 403, o token e invalidado e renovado automaticamente uma vez.
    """

    def __init__(self, config: ConfigDental | None = None) -> None:
        self.config = config or carregar_config_dental()
        _identidade = self.config.client_id.encode()
        self._cache_key = "dental_token_" + hashlib.sha256(_identidade).hexdigest()[:24]

    # ------------------------------------------------------------------
    # Pacientes
    # ------------------------------------------------------------------

    def listar_pacientes(
        self, clinic_id: int, page: int = 1, q: str = ""
    ) -> dict[str, Any]:
        """Consulta a listagem paginada de pacientes do Dental Office."""

        params = urlencode({"q": q, "page": page, "clinic_id": clinic_id})
        return self._get_autenticado(f"customers?{params}")

    def buscar_detalhes_paciente(self, id_dental: int | str) -> dict[str, Any]:
        """Busca dados completos de um paciente via GET /customers/{id}.

        Retorna CPF, RG, data de nascimento, endereco e dados do responsavel
        legal. Esses campos nao estao disponiveis na listagem paginada.
        """

        return self._get_autenticado(f"customers/{id_dental}")

    def listar_usuarios(
        self, user_group: int, page: int = 1, q: str = ""
    ) -> dict[str, Any]:
        """Consulta a listagem paginada de usuarios do Dental Office por grupo."""

        params = urlencode({"q": q, "user_group": user_group, "page": page})
        return self._get_autenticado(f"users?{params}")

    # ------------------------------------------------------------------
    # Documentos
    # ------------------------------------------------------------------

    def enviar_documento_paciente(
        self,
        id_dental: int | str,
        arquivo_bytes: bytes,
        nome: str,
        descricao: str = "",
        tag_list: str = "contrato",
    ) -> dict[str, Any]:
        """Envia um documento para a ficha do paciente no Dental Office.

        Usa multipart/form-data com os bytes do arquivo diretamente.
        O endpoint POST /customers/{id}/docs retorna HTTP 201 em caso de sucesso.
        """

        url = self.config.base_url.rstrip("/") + f"/customers/{id_dental}/docs"
        campos = {"customer_doc[name]": nome}
        if descricao:
            campos["customer_doc[description]"] = descricao
        if tag_list:
            campos["customer_doc[tag_list]"] = tag_list
        arquivos = {
            "customer_doc[file]": (nome, "application/octet-stream", arquivo_bytes)
        }
        return self._post_multipart_autenticado(url, campos, arquivos)

    # ------------------------------------------------------------------
    # Autenticacao
    # ------------------------------------------------------------------

    def _autenticar(self) -> str:
        """Retorna o token ativo, buscando do cache ou renovando se necessario."""

        token: str | None = cache.get(self._cache_key)
        if token:
            return token
        return self._renovar_token()

    def _renovar_token(self) -> str:
        """Autentica no Dental Office, salva o token no cache e o retorna."""

        data = self._post_json(
            self.config.auth_url,
            {"client_id": self.config.client_id, "secret": self.config.secret},
        )

        token = data.get("token")
        if not token:
            raise DentalAPIError(
                f"Campo 'token' ausente na resposta de autenticacao: {data}"
            )

        cache.set(self._cache_key, str(token), _DENTAL_TOKEN_TTL)
        return str(token)

    # ------------------------------------------------------------------
    # HTTP base
    # ------------------------------------------------------------------

    def _get_autenticado(self, path: str) -> Any:
        """Executa GET autenticado, renovando o token em caso de 401/403."""

        token = self._autenticar()
        try:
            return self._get_json(path, token=token)
        except DentalAPIError as exc:
            mensagem = str(exc)
            if "Erro HTTP 401" in mensagem or "Erro HTTP 403" in mensagem:
                cache.delete(self._cache_key)
                token = self._renovar_token()
                return self._get_json(path, token=token)
            raise

    def _post_autenticado(self, url: str, payload: dict[str, Any]) -> Any:
        """Executa POST JSON autenticado com URL absoluta; renova token em 401/403."""

        token = self._autenticar()
        try:
            return self._post_json(url, payload, token=token)
        except DentalAPIError as exc:
            mensagem = str(exc)
            if "Erro HTTP 401" in mensagem or "Erro HTTP 403" in mensagem:
                cache.delete(self._cache_key)
                token = self._renovar_token()
                return self._post_json(url, payload, token=token)
            raise

    def _post_multipart_autenticado(
        self,
        url: str,
        campos: dict[str, str],
        arquivos: dict[str, tuple[str, str, bytes]],
    ) -> Any:
        """Executa POST multipart/form-data autenticado, renovando token em 401/403.

        ``campos`` é um dicionário nome→valor de campos de texto.
        ``arquivos`` é nome→(filename, content_type, bytes).
        """

        token = self._autenticar()
        try:
            return self._post_multipart(url, campos, arquivos, token=token)
        except DentalAPIError as exc:
            mensagem = str(exc)
            if "Erro HTTP 401" in mensagem or "Erro HTTP 403" in mensagem:
                cache.delete(self._cache_key)
                token = self._renovar_token()
                return self._post_multipart(url, campos, arquivos, token=token)
            raise

    def _post_multipart(
        self,
        url: str,
        campos: dict[str, str],
        arquivos: dict[str, tuple[str, str, bytes]],
        token: str | None = None,
    ) -> Any:
        """Envia POST multipart/form-data e converte a resposta para objeto Python."""

        import uuid as _uuid

        boundary = ("----FormBoundary" + _uuid.uuid4().hex).encode("ascii")

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

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary.decode('ascii')}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(url, data=body, headers=headers, method="POST")
        return self._executar_request(request)

    def _get_json(self, path: str, token: str) -> Any:
        """Envia GET com Bearer token e converte a resposta para objeto Python."""

        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="GET",
        )
        return self._executar_request(request)

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        token: str | None = None,
    ) -> Any:
        """Envia POST JSON e converte a resposta para objeto Python."""

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._executar_request(request)

    def _executar_request(self, request: Request) -> Any:
        """Abre a conexao HTTP respeitando TLS e proxy, retorna JSON."""

        context = None if self.config.verify_tls else ssl._create_unverified_context()

        try:
            if self.config.use_proxy:
                response_context = {"context": context} if context else {}
                response = urlopen(
                    request, timeout=self.config.timeout, **response_context
                )
            else:
                handlers: list[Any] = [ProxyHandler({})]
                if context:
                    handlers.append(HTTPSHandler(context=context))
                response = build_opener(*handlers).open(
                    request, timeout=self.config.timeout
                )

            with response:
                body = response.read().decode("utf-8")

        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DentalAPIError(
                f"Erro HTTP {exc.code} ao consultar Dental Office: {detail}"
            ) from exc
        except URLError as exc:
            raise DentalAPIError(
                f"Falha de conexao ao consultar Dental Office: {exc.reason}"
            ) from exc

        if not body.strip():
            return {}

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            trecho = body[:200].replace("\n", " ")
            raise DentalAPIError(
                f"A API do Dental Office retornou resposta nao-JSON: {trecho!r}"
            ) from exc


def normalizar_paciente(item: dict[str, Any]) -> PacienteDental | None:
    """Converte um registro bruto do Dental Office em ``PacienteDental``.

    Retorna ``None`` quando o registro nao possui id ou nome valido.
    """

    id_ = item.get("id")
    nome = (item.get("name") or "").strip()
    if not id_ or not nome:
        return None

    celular = ""
    contatos = item.get("contacts_attributes") or []
    if contatos:
        primeiro = contatos[0]
        celular = (primeiro.get("cellphone") or primeiro.get("phone") or "").strip()

    return PacienteDental(
        id=int(id_),
        nome=nome,
        celular=celular,
        ativo=bool(item.get("active", True)),
    )


def normalizar_aluno_lab(item: dict[str, Any]) -> AlunoLabDental | None:
    """Converte um registro bruto de usuario do Dental Office em ``AlunoLabDental``.

    Retorna ``None`` quando o registro nao possui id ou nome valido.
    O campo deleted_at indica se o usuario foi removido (ativo=False).
    """

    id_ = item.get("id")
    nome = (item.get("name") or "").strip()
    if not id_ or not nome:
        return None

    celular = ""
    contatos = item.get("contacts_attributes") or []
    if contatos:
        primeiro = contatos[0]
        celular = (primeiro.get("cellphone") or primeiro.get("phone") or "").strip()

    ativo = item.get("deleted_at") is None

    return AlunoLabDental(
        id=int(id_),
        nome=nome,
        celular=celular,
        ativo=ativo,
    )


def normalizar_paciente_detalhado(data: dict[str, Any]) -> dict[str, Any]:
    """Extrai campos enriquecidos da resposta do endpoint GET /customers/{id}.

    Retorna um dicionario com os campos adicionais do modelo Paciente
    (cpf, rg, data_nascimento, endereco_*, nome_responsavel, cpf_responsavel).
    Nenhum campo e obrigatorio — valores ausentes ficam como string vazia ou None.
    """

    campos: dict[str, Any] = {}

    # Documento: CPF e RG
    doc = data.get("document_attributes") or {}
    cpf_raw = (doc.get("cpf") or "").strip()
    campos["cpf"] = _formatar_cpf(cpf_raw)
    campos["rg"] = (doc.get("rg") or "").strip()

    # Data de nascimento (formato ISO: YYYY-MM-DD)
    from datetime import date as _date

    nascimento_raw = (data.get("birth_date") or "").strip()
    try:
        campos["data_nascimento"] = (
            _date.fromisoformat(nascimento_raw) if nascimento_raw else None
        )
    except ValueError:
        campos["data_nascimento"] = None

    # Endereço (primeiro da lista)
    enderecos = data.get("addresses_attributes") or []
    if enderecos:
        end = enderecos[0]
        campos["endereco_logradouro"] = (end.get("street") or "").strip()
        campos["endereco_numero"] = str(end.get("number") or "").strip()
        campos["endereco_complemento"] = (end.get("complement") or "").strip()
        campos["endereco_bairro"] = (end.get("neighborhood") or "").strip()
        campos["endereco_cidade"] = (end.get("city") or "").strip()
        campos["endereco_estado"] = (end.get("state") or "").strip()[:2]
        campos["endereco_cep"] = (end.get("zipcode") or "").strip()
    else:
        for campo in (
            "endereco_logradouro",
            "endereco_numero",
            "endereco_complemento",
            "endereco_bairro",
            "endereco_cidade",
            "endereco_estado",
            "endereco_cep",
        ):
            campos[campo] = ""

    # Responsável legal (mãe tem prioridade; usado para menores de idade)
    mae_nome = (data.get("mother_name") or "").strip()
    pai_nome = (data.get("father_name") or "").strip()
    campos["nome_responsavel"] = mae_nome or pai_nome

    mae_cpf = (data.get("mother_cpf") or "").strip()
    pai_cpf = (data.get("father_cpf") or "").strip()
    campos["cpf_responsavel"] = _formatar_cpf(mae_cpf or pai_cpf)

    # E-mail (primeiro contato que tenha o campo preenchido)
    email = ""
    for contato in data.get("contacts_attributes") or []:
        candidato = (contato.get("email") or "").strip()
        if candidato:
            email = candidato
            break
    campos["email"] = email

    return campos


def _formatar_cpf(cpf_raw: str) -> str:
    """Formata sequencia numerica de CPF para 000.000.000-00."""

    digitos = "".join(c for c in cpf_raw if c.isdigit())
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return cpf_raw


def _ler_booleano(nome: str, padrao: bool = False) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "yes", "sim", "on"}
