"""Servicos de sincronizacao entre a CME e a API Eduq.

Este modulo orquestra consultas ao cliente Eduq, normaliza dados recebidos e
grava turmas, alunos e localizacoes no banco local.
"""

from dataclasses import dataclass, field
from time import sleep
from typing import Any

from django.db import transaction
from django.utils import timezone

from gestao_cme.integrations.eduq import (
    AlunoEduq,
    EduqAPIError,
    EduqClient,
    TurmaEduq,
    normalizar_aluno,
    normalizar_turma,
)
from gestao_cme.models import Aluno, OrigemDados, Turma
from gestao_cme.utils import normalizar_texto


@dataclass
class SyncResumo:
    """Resumo quantitativo de uma etapa de sincronizacao.

    Guarda contadores de registros criados, atualizados, ignorados e mensagens
    de erro acumuladas durante o processamento de turmas ou alunos.
    """

    criados: int = 0
    atualizados: int = 0
    ignorados: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def total_processado(self) -> int:
        """Calcula o total de itens tratados, incluindo erros."""

        return self.criados + self.atualizados + self.ignorados + len(self.erros)


@dataclass
class SyncEduqResultado:
    """Resultado completo de uma sincronizacao com o Eduq.

    Agrupa os resumos independentes de turmas e alunos para que chamadores
    possam apresentar indicadores separados por tipo de cadastro.
    """

    turmas: SyncResumo = field(default_factory=SyncResumo)
    alunos: SyncResumo = field(default_factory=SyncResumo)


def sincronizar_eduq(
    client: EduqClient | None = None,
    sincronizar_turmas: bool = True,
    sincronizar_alunos: bool = True,
    turma_codigos: list[str] | None = None,
    intervalo_consultas: float = 0,
) -> SyncEduqResultado:
    """Sincroniza turmas e/ou alunos usando o cliente Eduq informado.

    Quando turmas sao sincronizadas, seus codigos podem ser reaproveitados para
    buscar alunos. Caso contrario, a rotina usa os codigos recebidos ou as
    turmas Eduq ja ativas no banco local. Todo o processamento ocorre dentro de
    uma transacao atomica.
    """

    client = client or EduqClient()
    resultado = SyncEduqResultado()

    with transaction.atomic():
        turmas_eduq = []
        if sincronizar_turmas:
            turmas_eduq = client.listar_turmas()
            resultado.turmas = sincronizar_turmas_eduq(turmas_eduq)
        if sincronizar_alunos:
            if turma_codigos:
                codigos_para_alunos = turma_codigos
            elif turmas_eduq:
                codigos_para_alunos = [turma.codigo for turma in turmas_eduq]
            else:
                codigos_para_alunos = list(
                    Turma.objects.filter(
                        ativo=True, origem=OrigemDados.EDUQ
                    ).values_list(
                        "codigo",
                        flat=True,
                    )
                )

            alunos_eduq = []
            for index, codigo_turma in enumerate(codigos_para_alunos):
                try:
                    alunos_eduq.extend(client.listar_alunos(codigo_turma))
                except EduqAPIError as exc:
                    resultado.alunos.erros.append(f"Turma {codigo_turma}: {exc}")
                if intervalo_consultas and index < len(codigos_para_alunos) - 1:
                    sleep(intervalo_consultas)
            resumo_alunos = sincronizar_alunos_eduq(alunos_eduq)
            resultado.alunos.criados += resumo_alunos.criados
            resultado.alunos.atualizados += resumo_alunos.atualizados
            resultado.alunos.ignorados += resumo_alunos.ignorados
            resultado.alunos.erros.extend(resumo_alunos.erros)

    return resultado


def sincronizar_turmas_eduq(turmas_raw: list[dict[str, Any] | TurmaEduq]) -> SyncResumo:
    """Cria ou atualiza turmas locais a partir de registros vindos do Eduq.

    Cada item e normalizado para ``TurmaEduq`` antes do ``update_or_create``.
    Registros sem codigo ou nome entram no resumo como erro, sem interromper
    os demais itens.
    """

    resumo = SyncResumo()
    sincronizado_em = timezone.now()

    for index, raw in enumerate(turmas_raw, start=1):
        try:
            turma = normalizar_turma(raw)
            if turma is None:
                raise ValueError("Turma sem codigo ou nome.")
            _, created = Turma.objects.update_or_create(
                codigo=turma.codigo,
                defaults={
                    "nome": turma.nome,
                    "curso": turma.curso,
                    "data_inicio": turma.data_inicio,
                    "data_fim": turma.data_fim,
                    "observacoes": turma.observacoes,
                    "ativo": turma.ativo,
                    "origem": OrigemDados.EDUQ,
                    "ultima_sincronizacao": sincronizado_em,
                },
            )
        except ValueError as exc:
            resumo.erros.append(f"Turma #{index}: {exc}")
            continue

        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def sincronizar_alunos_eduq(alunos_raw: list[dict[str, Any] | AlunoEduq]) -> SyncResumo:
    """Cria ou atualiza alunos locais a partir de registros vindos do Eduq.

    A rotina associa cada aluno a uma turma local pelo codigo informado pelo
    Eduq. Quando a turma nao existe ou o aluno nao possui dados minimos, o item
    e registrado como erro no resumo.
    """

    resumo = SyncResumo()
    sincronizado_em = timezone.now()
    turmas_por_codigo = {turma.codigo: turma for turma in Turma.objects.all()}

    for index, raw in enumerate(alunos_raw, start=1):
        try:
            aluno = normalizar_aluno(raw)
            if aluno is None:
                raise ValueError("Aluno sem matricula ou nome.")
        except ValueError as exc:
            resumo.erros.append(f"Aluno #{index}: {exc}")
            continue

        turma = None
        if aluno.turma_codigo:
            turma = turmas_por_codigo.get(aluno.turma_codigo)
            if turma is None:
                resumo.erros.append(
                    f"Aluno #{index}: turma {aluno.turma_codigo!r} nao encontrada."
                )
                continue

        _, created = Aluno.objects.update_or_create(
            matricula=aluno.matricula,
            defaults={
                "nome": aluno.nome,
                "cpf": aluno.cpf or None,
                "email": aluno.email,
                "telefone": aluno.telefone,
                "cidade": aluno.cidade,
                "uf": aluno.uf,
                "turma": turma,
                "ativo": aluno.ativo,
                "origem": OrigemDados.EDUQ,
                "ultima_sincronizacao": sincronizado_em,
            },
        )

        if created:
            resumo.criados += 1
        else:
            resumo.atualizados += 1

    return resumo


def sincronizar_localizacao_alunos_turma(
    turma: Turma,
    client: EduqClient | None = None,
) -> int:
    """Atualiza cidade e UF de alunos de uma turma consultando o Eduq.

    A correspondencia tenta matricula, CPF e nome normalizado, nessa ordem.
    Retorna a quantidade de alunos que tiveram algum campo de localizacao
    alterado.
    """

    client = client or EduqClient()
    alunos_eduq = client.listar_alunos(turma.codigo)
    if not alunos_eduq:
        return 0

    por_matricula = {aluno.matricula: aluno for aluno in alunos_eduq if aluno.matricula}
    por_cpf = {aluno.cpf: aluno for aluno in alunos_eduq if aluno.cpf}
    por_nome = {
        _normalizar_nome(aluno.nome): aluno for aluno in alunos_eduq if aluno.nome
    }
    atualizados = 0

    for aluno in Aluno.objects.filter(turma=turma):
        aluno_eduq = (
            por_matricula.get(aluno.matricula)
            or (por_cpf.get(aluno.cpf) if aluno.cpf else None)
            or por_nome.get(_normalizar_nome(aluno.nome))
        )
        if not aluno_eduq or not (aluno_eduq.cidade or aluno_eduq.uf):
            continue

        campos_atualizados = []
        if aluno.cidade != aluno_eduq.cidade:
            aluno.cidade = aluno_eduq.cidade
            campos_atualizados.append("cidade")
        if aluno.uf != aluno_eduq.uf:
            aluno.uf = aluno_eduq.uf
            campos_atualizados.append("uf")

        if campos_atualizados:
            aluno.ultima_sincronizacao = timezone.now()
            campos_atualizados.append("ultima_sincronizacao")
            aluno.save(update_fields=campos_atualizados)
            atualizados += 1

    return atualizados


def _normalizar_nome(nome: str) -> str:
    """Remove acentos, normaliza caixa e compacta espacos de um nome.

    Mesma normalizacao usada nas buscas por nome (ver ``gestao_cme.utils``).
    """

    return normalizar_texto(nome)
