"""Integracao com a API Eduq.

Este modulo carrega configuracao, autentica no Eduq, executa consultas
personalizadas e normaliza respostas externas para estruturas internas.
"""

import hashlib
import json
import ssl
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, urlopen

from django.conf import settings
from django.core.cache import cache

# Margem de 1h abaixo do limite real (24h) para evitar uso de token prestes a expirar
_EDUQ_TOKEN_TTL = 23 * 60 * 60


class EduqAPIError(Exception):
    """Erro de configuracao, autenticacao ou comunicacao com a API Eduq."""

    pass


@dataclass(frozen=True)
class ConfigEduq:
    """Configuracao necessaria para autenticar e consultar a API Eduq."""

    dominio: str
    usuario: str
    senha: str
    auth_url: str
    data_url: str
    consulta_turmas_id: int
    consulta_detalhes_turma_id: int
    verify_tls: bool
    timeout: int
    use_proxy: bool


@dataclass(frozen=True)
class TurmaEduq:
    """Representacao normalizada de uma turma recebida do Eduq."""

    codigo: str
    nome: str
    curso: str = ""
    data_inicio: date | None = None
    data_fim: date | None = None
    observacoes: str = ""
    ativo: bool = True


@dataclass(frozen=True)
class AlunoEduq:
    """Representacao normalizada de um aluno recebido do Eduq."""

    matricula: str
    nome: str
    cpf: str = ""
    email: str = ""
    telefone: str = ""
    cidade: str = ""
    uf: str = ""
    turma_codigo: str = ""
    ativo: bool = True


def carregar_config_eduq() -> ConfigEduq:
    """Monta a configuracao da API Eduq a partir de settings.

    Valida credenciais obrigatorias e converte opcoes como consulta, timeout,
    proxy e verificacao TLS para os tipos usados pelo cliente HTTP.
    """

    if not settings.EDUQ_CONFIGURADO:
        ausentes = [
            nome
            for nome, valor in (
                ("DOMINIO", settings.EDUQ_DOMINIO),
                ("USUARIO", settings.EDUQ_USUARIO),
                ("SENHA", settings.EDUQ_SENHA),
            )
            if not valor
        ]
        variaveis = ", ".join(f"EDUQ_{nome}" for nome in ausentes)
        raise EduqAPIError(f"Configure as variaveis de ambiente: {variaveis}")

    return ConfigEduq(
        dominio=settings.EDUQ_DOMINIO,
        usuario=settings.EDUQ_USUARIO,
        senha=settings.EDUQ_SENHA,
        auth_url=settings.EDUQ_AUTH_URL,
        data_url=settings.EDUQ_DATA_URL,
        consulta_turmas_id=settings.EDUQ_CONSULTA_TURMAS_ID,
        consulta_detalhes_turma_id=settings.EDUQ_CONSULTA_DETALHES_TURMA_ID,
        verify_tls=settings.EDUQ_VERIFY_TLS,
        timeout=settings.EDUQ_TIMEOUT,
        use_proxy=settings.EDUQ_USE_PROXY,
    )


class EduqClient:
    """Cliente HTTP minimo para autenticar e consultar dados no Eduq.

    O token de acesso e armazenado no cache Django com TTL de 23h para ser
    reutilizado entre instancias e requisicoes. Quando uma consulta retorna
    HTTP 401 ou 403, o token e invalidado e renovado automaticamente uma vez.
    """

    def __init__(self, config: ConfigEduq | None = None) -> None:
        """Inicializa o cliente com configuracao explicita ou do ambiente."""

        self.config = config or carregar_config_eduq()
        # Chave anonimizada: hash dos dados de identidade sem expor credenciais no cache
        _identidade = f"{self.config.dominio}:{self.config.usuario}".encode()
        self._cache_key = "eduq_token_" + hashlib.sha256(_identidade).hexdigest()[:24]

    def listar_turmas(self) -> list[TurmaEduq]:
        """Consulta turmas no Eduq e retorna apenas registros normalizados."""

        payload = {
            "consultaPersonalizada": {"id": self.config.consulta_turmas_id},
            "filtros": [],
        }
        data = self._consultar(payload)
        return [
            turma
            for turma in (normalizar_turma(item) for item in _encontrar_lista(data))
            if turma
        ]

    def listar_alunos(self, codigo_turma_eduq: str) -> list[AlunoEduq]:
        """Consulta alunos de uma turma Eduq e normaliza a resposta."""

        payload = {
            "consultaPersonalizada": {"id": self.config.consulta_detalhes_turma_id},
            "filtros": [{"chave": "filtroTurma", "valor": str(codigo_turma_eduq)}],
        }
        data = self._consultar(payload)
        detalhes = _extrair_resultado(data)
        alunos = detalhes if isinstance(detalhes, list) else _encontrar_lista(detalhes)
        return [
            aluno
            for aluno in (normalizar_aluno(item, codigo_turma_eduq) for item in alunos)
            if aluno
        ]

    def _autenticar(self) -> str:
        """Retorna o token ativo, buscando do cache ou renovando se necessario."""

        token: str | None = cache.get(self._cache_key)
        if token:
            return token
        return self._renovar_token()

    def _renovar_token(self) -> str:
        """Autentica no Eduq, salva o token no cache e o retorna."""

        data = self._post_json(
            self.config.auth_url,
            {
                "dominio": self.config.dominio,
                "usuario": self.config.usuario,
                "senha": self.config.senha,
            },
        )

        if not data.get("sucesso"):
            raise EduqAPIError(f"Falha na autenticacao Eduq: {data}")

        token = data.get("resultado", {}).get("token1")
        if not token:
            raise EduqAPIError("Token token1 nao encontrado na resposta da Eduq.")

        cache.set(self._cache_key, str(token), _EDUQ_TOKEN_TTL)
        return str(token)

    def _consultar(self, payload: dict[str, Any]) -> Any:
        """Executa uma consulta autenticada, renovando o token em caso de 401/403."""

        token = self._autenticar()
        try:
            return self._post_json(
                self.config.data_url, payload, headers={"token-auth": token}
            )
        except EduqAPIError as exc:
            mensagem = str(exc)
            if "Erro HTTP 401" in mensagem or "Erro HTTP 403" in mensagem:
                cache.delete(self._cache_key)
                token = self._renovar_token()
                return self._post_json(
                    self.config.data_url, payload, headers={"token-auth": token}
                )
            raise

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Envia POST JSON e converte a resposta da API para objeto Python."""

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **(headers or {}),
            },
            method="POST",
        )

        context = None if self.config.verify_tls else ssl._create_unverified_context()
        try:
            if self.config.use_proxy:
                response_context = {"context": context} if context else {}
                response = urlopen(
                    request,
                    timeout=self.config.timeout,
                    **response_context,
                )
            else:
                handlers = [ProxyHandler({})]
                if context:
                    handlers.append(HTTPSHandler(context=context))
                response = build_opener(*handlers).open(
                    request, timeout=self.config.timeout
                )
            with response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EduqAPIError(
                f"Erro HTTP {exc.code} ao consultar Eduq: {detail}"
            ) from exc
        except URLError as exc:
            raise EduqAPIError(
                f"Falha de conexao ao consultar Eduq: {exc.reason}"
            ) from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise EduqAPIError(
                "A API do Eduq retornou uma resposta que nao e JSON valido."
            ) from exc


def normalizar_turma(item: dict[str, Any] | TurmaEduq) -> TurmaEduq | None:
    """Converte um registro bruto do Eduq em ``TurmaEduq``.

    Aceita diferentes nomes de chave encontrados nas consultas personalizadas e
    retorna ``None`` quando nao ha dados minimos para identificar a turma.
    """

    if isinstance(item, TurmaEduq):
        return item

    turma_id = _primeiro_texto(
        item,
        (
            "id",
            "turma_id",
            "id_turma",
            "codigo",
            "codigo_turma",
            "cod_turma",
            "eduq_turma_id",
            "identificador da turma",
            "turmaid",
        ),
    )
    sigla = _primeiro_texto(item, ("sigla",))
    descricao = _primeiro_texto(item, ("descricao",))
    nome = _primeiro_texto(
        item,
        (
            "nome",
            "nome_turma",
            "turma",
            "descricao",
            "descricao_turma",
            "curso",
            "sigla",
        ),
    )

    if sigla and descricao:
        nome = f"{sigla} - {descricao}"

    nome = str(nome or turma_id).strip()
    turma_id = str(turma_id or nome).strip()
    if not turma_id or not nome:
        return None

    periodo = _primeiro_texto(item, ("periodo", "semestre", "modulo"))
    matriculas_ativas = _primeiro_texto(item, ("matriculas ativas",))
    return TurmaEduq(
        codigo=turma_id,
        nome=nome,
        curso=_primeiro_texto(item, ("curso", "nome_curso", "nomecurso", "descricao")),
        data_inicio=_primeira_data(
            item,
            ("data_inicio", "dataInicio", "inicio", "data de inicio"),
        ),
        data_fim=_primeira_data(
            item,
            ("data_fim", "dataFim", "fim", "data de finalizacao"),
        ),
        observacoes=_observacoes_turma(periodo, matriculas_ativas),
        ativo=_turma_ativa(item),
    )


def normalizar_aluno(
    item: dict[str, Any] | AlunoEduq,
    codigo_turma_eduq: str | None = None,
) -> AlunoEduq | None:
    """Converte um registro bruto do Eduq em ``AlunoEduq``.

    Usa varias chaves alternativas para matricula, nome, contato e localizacao.
    Quando nao ha matricula, cria um identificador derivado da turma e do nome.
    """

    if isinstance(item, AlunoEduq):
        return item

    nome = _primeiro_texto(item, ("nome", "aluno", "nome_completo", "name"))
    if not nome:
        return None

    codigo = _primeiro_texto(
        item,
        (
            "identificador",
            "matricula",
            "codigo",
            "codigo_eduq",
            "idAluno",
            "id",
            "cpf",
        ),
    )
    turma_codigo = codigo_turma_eduq or _turma_codigo(item)
    if not codigo:
        codigo = f"{turma_codigo}:{nome}"

    return AlunoEduq(
        matricula=codigo,
        nome=nome,
        cpf=_primeiro_texto(item, ("cpf", "documento")),
        email=_primeiro_texto(item, ("email", "e_mail")),
        telefone=_primeiro_texto(item, ("telefone", "celular", "celularsms", "fone")),
        cidade=_primeiro_texto(item, ("descricao", "cidade", "municipio", "local")),
        uf=_primeiro_texto(item, ("uf", "sigla_uf", "estado")),
        turma_codigo=str(turma_codigo),
        ativo=_primeiro_bool(item, ("ativo", "active", "status")),
    )


def _encontrar_lista(dados: Any) -> list[dict[str, Any]]:
    """Procura uma lista de dicionarios em respostas aninhadas da API."""

    if isinstance(dados, str):
        try:
            return _encontrar_lista(json.loads(dados))
        except json.JSONDecodeError:
            return []

    if isinstance(dados, list):
        return [item for item in dados if isinstance(item, dict)]
    if not isinstance(dados, dict):
        return []

    for chave in ("turmas", "dados", "resultado", "registros", "items", "data"):
        valor = dados.get(chave)
        if isinstance(valor, str):
            nested = _encontrar_lista(valor)
            if nested:
                return nested
        if isinstance(valor, list):
            return [item for item in valor if isinstance(item, dict)]
        if isinstance(valor, dict):
            nested = _encontrar_lista(valor)
            if nested:
                return nested

    return []


def _extrair_resultado(data: Any) -> Any:
    """Extrai e decodifica o campo ``resultado`` quando ele existe."""

    if not isinstance(data, dict) or "resultado" not in data:
        return data

    resultado = data.get("resultado")
    if isinstance(resultado, str):
        try:
            return json.loads(resultado)
        except json.JSONDecodeError:
            return resultado

    return resultado


def _normalizar_chave(chave: str) -> str:
    """Remove acentos e padroniza nomes de chaves para comparacao."""

    sem_acento = unicodedata.normalize("NFKD", str(chave))
    return sem_acento.encode("ascii", "ignore").decode("ascii").lower().strip()


def _primeiro_texto(item: dict[str, Any], chaves: tuple[str, ...]) -> str:
    """Retorna o primeiro valor textual encontrado entre chaves alternativas."""

    valores_por_chave = {
        _normalizar_chave(chave): valor for chave, valor in item.items()
    }
    for chave in chaves:
        valor = valores_por_chave.get(_normalizar_chave(chave))
        if valor is not None:
            return str(valor).strip()
    return ""


def _primeiro_bool(item: dict[str, Any], chaves: tuple[str, ...]) -> bool:
    """Retorna o primeiro valor booleano interpretavel entre chaves alternativas."""

    valores_por_chave = {
        _normalizar_chave(chave): valor for chave, valor in item.items()
    }
    for chave in chaves:
        valor = valores_por_chave.get(_normalizar_chave(chave))
        if isinstance(valor, bool):
            return valor
        if valor is not None:
            return str(valor).strip().lower() not in {"false", "0", "nao", "inativo"}
    return True


def _primeira_data(item: dict[str, Any], chaves: tuple[str, ...]) -> date | None:
    """Retorna a primeira data valida encontrada nas chaves informadas."""

    valor = _primeiro_texto(item, chaves)
    if not valor:
        return None

    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(valor[:19], formato).date()
        except ValueError:
            continue
    return None


def _observacoes_turma(periodo: str, matriculas_ativas: str) -> str:
    """Monta observacoes da turma com periodo e matriculas ativas."""

    partes = []
    if periodo:
        partes.append(f"Periodo: {periodo}")
    if matriculas_ativas:
        partes.append(f"Matriculas ativas no Eduq: {matriculas_ativas}")
    return " | ".join(partes)


def _turma_ativa(item: dict[str, Any]) -> bool:
    """Determina se a turma esta ativa a partir dos campos do Eduq."""

    matriculas_ativas = _primeiro_texto(item, ("matriculas ativas",))
    if matriculas_ativas:
        try:
            return int(matriculas_ativas) > 0
        except ValueError:
            pass
    return _primeiro_bool(item, ("ativo", "active", "status"))


def _turma_codigo(raw: dict[str, Any]) -> str:
    """Extrai o codigo da turma de um aluno ou objeto aninhado de turma."""

    codigo = _primeiro_texto(
        raw, ("turma_codigo", "codigoTurma", "codTurma", "idTurma")
    )
    if codigo:
        return codigo

    turma = raw.get("turma")
    if isinstance(turma, dict):
        return _primeiro_texto(turma, ("codigo", "codTurma", "id", "idTurma"))

    return ""
