from dataclasses import dataclass, field
from time import sleep
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.integrations.eduq import (
    AlunoEduq,
    EduqAPIError,
    EduqClient,
    TurmaEduq,
    normalizar_aluno,
    normalizar_turma,
)
from core.models import Aluno, OrigemDados, Turma


@dataclass
class SyncResumo:
    criados: int = 0
    atualizados: int = 0
    ignorados: int = 0
    erros: list[str] = field(default_factory=list)

    @property
    def total_processado(self) -> int:
        return self.criados + self.atualizados + self.ignorados + len(self.erros)


@dataclass
class SyncEduqResultado:
    turmas: SyncResumo = field(default_factory=SyncResumo)
    alunos: SyncResumo = field(default_factory=SyncResumo)


def sincronizar_eduq(
    client: EduqClient | None = None,
    sincronizar_turmas: bool = True,
    sincronizar_alunos: bool = True,
    turma_codigos: list[str] | None = None,
    intervalo_consultas: float = 0,
) -> SyncEduqResultado:
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
                    Turma.objects.filter(ativo=True, origem=OrigemDados.EDUQ).values_list(
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
