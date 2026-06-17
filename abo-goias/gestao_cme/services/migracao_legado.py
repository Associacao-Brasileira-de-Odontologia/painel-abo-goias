"""Servicos para migrar dados operacionais de planilhas legadas.

O modulo importa CSVs historicos de abrigos, kits, materiais e movimentacoes,
normalizando os valores antes de persisti-los nos modelos da CME.
"""

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from gestao_cme.models import (
    Abrigo,
    Aluno,
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    OrigemDados,
    Turma,
)


ARQUIVO_ABRIGOS = "Abrigos.csv"
ARQUIVO_ITENS_NAO_RETIRADOS = "Itens não retirados.csv"
ARQUIVO_MOVIMENTACAO = "Relatório de movimentação.csv"
ARQUIVO_KITS = "Kits.csv"
ARQUIVO_MATERIAIS = "Materiais para empréstimo.csv"


@dataclass
class MigracaoResumo:
    """Resumo de uma importacao de arquivo legado.

    Guarda quantos registros foram criados, atualizados e quais erros foram
    encontrados durante a leitura ou persistencia de um CSV especifico.
    """

    criados: int = 0
    atualizados: int = 0
    erros: list[str] = field(default_factory=list)

    def somar(self, other: "MigracaoResumo") -> None:
        """Acumula os contadores e erros de outro resumo de migracao."""

        self.criados += other.criados
        self.atualizados += other.atualizados
        self.erros.extend(other.erros)


@dataclass
class MigracaoLegadoResultado:
    """Resultado consolidado da migracao de todos os arquivos legados.

    Separa os resumos por dominio operacional para facilitar mensagens de
    comando, auditoria e investigacao de erros por tipo de dado.
    """

    abrigos: MigracaoResumo = field(default_factory=MigracaoResumo)
    kits: MigracaoResumo = field(default_factory=MigracaoResumo)
    materiais: MigracaoResumo = field(default_factory=MigracaoResumo)
    movimentacoes: MigracaoResumo = field(default_factory=MigracaoResumo)


def migrar_dados_legado(diretorio: Path | str) -> MigracaoLegadoResultado:
    """Executa a migracao completa a partir de um diretorio de CSVs legados.

    Processa abrigos, kits, materiais e movimentacoes em uma transacao atomica.
    Cada etapa recebe o arquivo esperado pelo nome historico e devolve um
    resumo separado dentro do resultado consolidado.
    """

    diretorio = Path(diretorio)
    resultado = MigracaoLegadoResultado()

    with transaction.atomic():
        resultado.abrigos = migrar_abrigos(diretorio / ARQUIVO_ABRIGOS)
        resultado.kits = migrar_kits(diretorio / ARQUIVO_KITS)
        resultado.materiais = migrar_materiais(diretorio / ARQUIVO_MATERIAIS)
        resultado.movimentacoes.somar(
            migrar_movimentacoes(diretorio / ARQUIVO_MOVIMENTACAO)
        )
        resultado.movimentacoes.somar(
            migrar_movimentacoes(diretorio / ARQUIVO_ITENS_NAO_RETIRADOS)
        )

    return resultado


def migrar_abrigos(path: Path) -> MigracaoResumo:
    """Importa abrigos a partir do CSV de ocupacao legado.

    Agrupa linhas pelo identificador do abrigo e considera o abrigo ocupado se
    qualquer linha correspondente indicar ocupacao.
    """

    resumo = MigracaoResumo()
    sincronizado_em = timezone.now()
    agrupados: dict[str, bool] = {}

    for index, row in enumerate(_ler_csv(path), start=2):
        identificador = _texto(row, "Identificador")
        if not identificador:
            resumo.erros.append(f"{path.name} linha {index}: abrigo sem identificador.")
            continue
        agrupados[identificador] = agrupados.get(identificador, False) or _bool(
            _texto(row, "Ocupado")
        )

    for identificador, ocupado in agrupados.items():
        _, created = Abrigo.objects.update_or_create(
            identificador=identificador,
            defaults={
                "ocupado": ocupado,
                "ativo": True,
                "origem": OrigemDados.LEGADO,
                "ultima_sincronizacao": sincronizado_em,
            },
        )
        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def migrar_kits(path: Path) -> MigracaoResumo:
    """Importa kits legados criando codigos estaveis a partir do nome.

    Cada linha valida gera ou atualiza um kit com origem LEGADO, quantidade e
    data de sincronizacao da rodada atual.
    """

    resumo = MigracaoResumo()
    sincronizado_em = timezone.now()

    for index, row in enumerate(_ler_csv(path), start=2):
        nome = _texto(row, "Kit")
        if not nome:
            resumo.erros.append(f"{path.name} linha {index}: kit sem nome.")
            continue
        _, created = Kit.objects.update_or_create(
            codigo=_codigo_estavel("KITLEG", nome),
            defaults={
                "nome": nome,
                "quantidade": _inteiro(_texto(row, "Quantidade")),
                "descricao": "",
                "ativo": True,
                "origem": OrigemDados.LEGADO,
                "ultima_sincronizacao": sincronizado_em,
            },
        )
        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def migrar_materiais(path: Path) -> MigracaoResumo:
    """Importa materiais legados e vincula cada item ao kit correspondente.

    A rotina usa codigos estaveis para materiais e kits, cria kits auxiliares
    quando necessario e atualiza a tabela intermediaria KitMaterial.
    """

    resumo = MigracaoResumo()
    sincronizado_em = timezone.now()

    for index, row in enumerate(_ler_csv(path), start=2):
        nome = _texto(row, "Material")
        identificacao = _texto(row, "Identificação")
        rotulo_kit = _texto(row, "Kit")
        if not nome or not rotulo_kit:
            resumo.erros.append(f"{path.name} linha {index}: material sem nome ou kit.")
            continue

        kit = Kit.objects.filter(codigo=_codigo_estavel("KITLEG", nome)).first()
        if kit is None:
            kit, _ = Kit.objects.update_or_create(
                codigo=_codigo_estavel("KITLEG", nome),
                defaults={
                    "nome": nome,
                    "quantidade": 0,
                    "origem": OrigemDados.LEGADO,
                    "ultima_sincronizacao": sincronizado_em,
                },
            )

        disponivel = _bool(_texto(row, "Disponivel"))
        _, created = Material.objects.update_or_create(
            codigo=_codigo_estavel("MATLEG", rotulo_kit),
            defaults={
                "nome": nome,
                "descricao": rotulo_kit,
                "identificacao": identificacao,
                "rotulo_kit": rotulo_kit,
                "disponivel": disponivel,
                "ativo": _bool(_texto(row, "Ativo")),
                "origem": OrigemDados.LEGADO,
                "ultima_sincronizacao": sincronizado_em,
            },
        )
        material = Material.objects.get(codigo=_codigo_estavel("MATLEG", rotulo_kit))
        KitMaterial.objects.update_or_create(
            kit=kit,
            material=material,
            defaults={"quantidade": 1},
        )

        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def migrar_movimentacoes(path: Path) -> MigracaoResumo:
    """Importa historico de entradas, saidas e retiradas pendentes.

    Normaliza aluno, turma, material, data e tipo de movimentacao, preservando
    dados textuais do CSV mesmo quando nao ha cadastro relacionado no banco.
    """

    resumo = MigracaoResumo()
    alunos_por_nome = {_normalizar(aluno.nome): aluno for aluno in Aluno.objects.all()}
    alunos_por_codigo = {aluno.matricula: aluno for aluno in Aluno.objects.all()}
    turmas_por_nome = {_normalizar(turma.nome): turma for turma in Turma.objects.all()}
    materiais_por_codigo = {material.codigo: material for material in Material.objects.all()}

    for index, row in enumerate(_ler_csv(path), start=2):
        try:
            data_hora = _parse_data(_texto(row, "Data"))
            tipo = _tipo_movimentacao(_texto(row, "Movimentação"))
            aluno_codigo, aluno_nome = _parse_aluno(_texto(row, "Nome"))
            turma_nome = _texto(row, "Turma")
            pacote_codigo = _texto(row, "Pacote")
            if not pacote_codigo:
                raise ValueError("movimentacao sem pacote.")

            row_hash = _row_hash(path.name, row)
            aluno = alunos_por_codigo.get(aluno_codigo) or alunos_por_nome.get(
                _normalizar(aluno_nome)
            )
            turma = turmas_por_nome.get(_normalizar(turma_nome))
            material = materiais_por_codigo.get(pacote_codigo)

            _, created = Movimentacao.objects.update_or_create(
                row_hash=row_hash,
                defaults={
                    "data_hora": data_hora,
                    "tipo": tipo,
                    "aluno": aluno,
                    "turma": turma,
                    "material": material,
                    "aluno_codigo_externo": aluno_codigo,
                    "aluno_nome": aluno_nome,
                    "turma_nome": turma_nome,
                    "pacote_codigo": pacote_codigo,
                    "retirado": _retirado(row),
                    "arquivo_origem": path.name,
                    "origem": OrigemDados.LEGADO,
                    "ativo": True,
                },
            )
        except ValueError as exc:
            resumo.erros.append(f"{path.name} linha {index}: {exc}")
            continue

        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def _ler_csv(path: Path) -> list[dict[str, str]]:
    """Le um CSV UTF-8 com BOM opcional e retorna linhas como dicionarios."""

    if not path.exists():
        raise ValueError(f"Arquivo nao encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _texto(row: dict[str, Any], key: str) -> str:
    """Extrai um campo textual de uma linha, removendo espacos externos."""

    value = row.get(key)
    return "" if value is None else str(value).strip()


def _bool(value: str) -> bool:
    """Converte valores textuais comuns de verdadeiro para booleano."""

    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _inteiro(value: str) -> int:
    """Converte texto para inteiro, usando zero quando o valor e invalido."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _codigo_estavel(prefix: str, value: str) -> str:
    """Gera um codigo deterministico com prefixo e hash curto do valor."""

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def _normalizar(value: str) -> str:
    """Normaliza texto para comparacoes flexiveis entre planilha e banco."""

    sem_acento = unicodedata.normalize("NFKD", value or "")
    ascii_value = sem_acento.encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"[^A-Z0-9]+", " ", ascii_value).strip()


def _parse_data(value: str) -> datetime:
    """Interpreta datas legadas nos formatos conhecidos e aplica timezone."""

    for fmt in ("%d/%m/%Y, %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue
    raise ValueError(f"data invalida: {value!r}.")


def _tipo_movimentacao(value: str) -> str:
    """Converte o texto do CSV para uma escolha de Movimentacao.Tipo."""

    normalized = _normalizar(value)
    if normalized == "SAIDA":
        return Movimentacao.Tipo.SAIDA
    if normalized == "ENTRADA":
        return Movimentacao.Tipo.ENTRADA
    raise ValueError(f"tipo de movimentacao invalido: {value!r}.")


def _parse_aluno(value: str) -> tuple[str, str]:
    """Separa codigo externo e nome do aluno no formato legado."""

    cleaned = value.strip().lstrip("-").strip()
    match = re.match(r"^(\d+)\s*-\s*(.+)$", cleaned)
    if match:
        return match.group(1), match.group(2).strip()
    return "", cleaned


def _retirado(row: dict[str, str]) -> bool | None:
    """Determina o status de retirada conforme colunas presentes no CSV."""

    if "Retirado" in row and _texto(row, "Retirado"):
        return _bool(_texto(row, "Retirado"))
    if "Entregar" in row and _texto(row, "Entregar"):
        return False
    return None


def _row_hash(file_name: str, row: dict[str, str]) -> str:
    """Calcula hash unico e reprodutivel para uma linha de arquivo legado."""

    parts = [file_name]
    for key in sorted(row):
        parts.append(f"{key}={row.get(key, '')}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
