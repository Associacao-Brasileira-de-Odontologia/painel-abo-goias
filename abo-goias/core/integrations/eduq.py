import json
import os
import ssl
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, urlopen

from django.conf import settings


class EduqAPIError(Exception):
    pass


@dataclass(frozen=True)
class ConfigEduq:
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
    codigo: str
    nome: str
    curso: str = ""
    data_inicio: date | None = None
    data_fim: date | None = None
    observacoes: str = ""
    ativo: bool = True


@dataclass(frozen=True)
class AlunoEduq:
    matricula: str
    nome: str
    cpf: str = ""
    email: str = ""
    telefone: str = ""
    cidade: str = ""
    uf: str = ""
    turma_codigo: str = ""
    ativo: bool = True


def carregar_arquivo_env(caminho: Path | None = None) -> None:
    caminhos = []
    if caminho:
        caminhos.append(caminho)
    caminhos.extend(
        (
            settings.BASE_DIR / ".env",
            settings.BASE_DIR.parent / ".env",
            settings.BASE_DIR / ".env.example",
            settings.BASE_DIR.parent / ".env.example",
        )
    )

    for arquivo in caminhos:
        if not arquivo.exists():
            continue
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def carregar_config_eduq() -> ConfigEduq:
    carregar_arquivo_env()

    credenciais = {
        "dominio": os.getenv("EDUQ_DOMINIO", "").strip(),
        "usuario": os.getenv("EDUQ_USUARIO", "").strip(),
        "senha": os.getenv("EDUQ_SENHA", "").strip(),
    }
    ausentes = [nome for nome, valor in credenciais.items() if not valor]
    if ausentes:
        variaveis = ", ".join(f"EDUQ_{nome.upper()}" for nome in ausentes)
        raise EduqAPIError(f"Configure as variaveis de ambiente: {variaveis}")

    return ConfigEduq(
        dominio=credenciais["dominio"],
        usuario=credenciais["usuario"],
        senha=credenciais["senha"],
        auth_url=os.getenv("EDUQ_AUTH_URL", settings.EDUQ_AUTH_URL).strip(),
        data_url=os.getenv("EDUQ_DATA_URL", settings.EDUQ_DATA_URL).strip(),
        consulta_turmas_id=int(os.getenv("EDUQ_CONSULTA_TURMAS_ID", settings.EDUQ_CONSULTA_TURMAS_ID)),
        consulta_detalhes_turma_id=int(
            os.getenv("EDUQ_CONSULTA_DETALHES_TURMA_ID", settings.EDUQ_CONSULTA_DETALHES_TURMA_ID)
        ),
        verify_tls=_ler_booleano("EDUQ_VERIFY_TLS", settings.EDUQ_VERIFY_TLS),
        timeout=int(os.getenv("EDUQ_TIMEOUT", settings.EDUQ_TIMEOUT)),
        use_proxy=_ler_booleano("EDUQ_USE_PROXY", settings.EDUQ_USE_PROXY),
    )


class EduqClient:
    def __init__(self, config: ConfigEduq | None = None):
        self.config = config or carregar_config_eduq()
        self._token: str | None = None

    def listar_turmas(self) -> list[TurmaEduq]:
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
        if self._token:
            return self._token

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

        self._token = str(token)
        return self._token

    def _consultar(self, payload: dict[str, Any]) -> Any:
        token = self._autenticar()
        return self._post_json(self.config.data_url, payload, headers={"token-auth": token})

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
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
                response = build_opener(*handlers).open(request, timeout=self.config.timeout)
            with response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EduqAPIError(f"Erro HTTP {exc.code} ao consultar Eduq: {detail}") from exc
        except URLError as exc:
            raise EduqAPIError(f"Falha de conexao ao consultar Eduq: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise EduqAPIError("A API do Eduq retornou uma resposta que nao e JSON valido.") from exc


def normalizar_turma(item: dict[str, Any] | TurmaEduq) -> TurmaEduq | None:
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
        ("nome", "nome_turma", "turma", "descricao", "descricao_turma", "curso", "sigla"),
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
    sem_acento = unicodedata.normalize("NFKD", str(chave))
    return sem_acento.encode("ascii", "ignore").decode("ascii").lower().strip()


def _primeiro_texto(item: dict[str, Any], chaves: tuple[str, ...]) -> str:
    valores_por_chave = {_normalizar_chave(chave): valor for chave, valor in item.items()}
    for chave in chaves:
        valor = valores_por_chave.get(_normalizar_chave(chave))
        if valor is not None:
            return str(valor).strip()
    return ""


def _primeiro_bool(item: dict[str, Any], chaves: tuple[str, ...]) -> bool:
    valores_por_chave = {_normalizar_chave(chave): valor for chave, valor in item.items()}
    for chave in chaves:
        valor = valores_por_chave.get(_normalizar_chave(chave))
        if isinstance(valor, bool):
            return valor
        if valor is not None:
            return str(valor).strip().lower() not in {"false", "0", "nao", "inativo"}
    return True


def _primeira_data(item: dict[str, Any], chaves: tuple[str, ...]) -> date | None:
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
    partes = []
    if periodo:
        partes.append(f"Periodo: {periodo}")
    if matriculas_ativas:
        partes.append(f"Matriculas ativas no Eduq: {matriculas_ativas}")
    return " | ".join(partes)


def _turma_ativa(item: dict[str, Any]) -> bool:
    matriculas_ativas = _primeiro_texto(item, ("matriculas ativas",))
    if matriculas_ativas:
        try:
            return int(matriculas_ativas) > 0
        except ValueError:
            pass
    return _primeiro_bool(item, ("ativo", "active", "status"))


def _turma_codigo(raw: dict[str, Any]) -> str:
    codigo = _primeiro_texto(raw, ("turma_codigo", "codigoTurma", "codTurma", "idTurma"))
    if codigo:
        return codigo

    turma = raw.get("turma")
    if isinstance(turma, dict):
        return _primeiro_texto(turma, ("codigo", "codTurma", "id", "idTurma"))

    return ""


def _ler_booleano(nome: str, padrao: bool = False) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "yes", "sim", "on"}
