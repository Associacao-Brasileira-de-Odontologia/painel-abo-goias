"""Servico de sincronizacao de alunos/turmas entre o Eduq e o banco local.

Reusa o cliente HTTP do Eduq ja existente em ``gestao_cme.integrations.eduq``
(mesmo usado pelo proprio gestao_cme e pelo app ``identificadores``) — o
laboratorio so precisava de uma fonte de dados correta para AlunoLab, nao de
um cliente HTTP proprio. As tabelas locais (``TurmaLab``/``AlunoLab``)
continuam exclusivas do gestao_lab, sem compartilhar linhas com
``gestao_cme.Turma``/``Aluno``.
"""

from __future__ import annotations

import time
from typing import TypedDict

from django.utils import timezone
from gestao_lab.models import AlunoLab, OrigemDados, TurmaLab

from gestao_cme.integrations.eduq import (
    AlunoEduq,
    EduqAPIError,
    EduqClient,
    TurmaEduq,
)

__all__ = [
    "EduqAPIError",
    "ResultadoSync",
    "listar_turmas_eduq",
    "sincronizar_turma_eduq",
    "sincronizar_todas_turmas_eduq",
    "executar_sync_alunos_e_registrar",
]


class ResultadoSync(TypedDict):
    turmas_criadas: int
    turmas_atualizadas: int
    alunos_criados: int
    alunos_atualizados: int
    alunos_ignorados: int


def _resultado_vazio() -> ResultadoSync:
    return {
        "turmas_criadas": 0,
        "turmas_atualizadas": 0,
        "alunos_criados": 0,
        "alunos_atualizados": 0,
        "alunos_ignorados": 0,
    }


def listar_turmas_eduq() -> list[TurmaEduq]:
    """Lista as turmas disponiveis no Eduq, sem gravar nada localmente.

    Usada para montar o seletor de "qual turma sincronizar" quando a busca de
    aluno (local-only) nao encontra ninguem — ver
    ``views.sincronizar_turma_aluno_busca``.
    """

    return EduqClient().listar_turmas()


def _upsert_turma(turma_eduq: TurmaEduq) -> tuple[TurmaLab, bool]:
    return TurmaLab.objects.update_or_create(
        codigo=turma_eduq.codigo,
        defaults={
            "nome": turma_eduq.nome,
            "origem": OrigemDados.EDUQ,
            "ativo": turma_eduq.ativo,
            "ultima_sincronizacao": timezone.now(),
        },
    )


def _upsert_alunos(
    alunos_eduq: list[AlunoEduq], turma_local: TurmaLab
) -> tuple[int, int, int]:
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    for aluno_eduq in alunos_eduq:
        if not aluno_eduq.matricula or not aluno_eduq.nome:
            ignorados += 1
            continue

        _, criado = AlunoLab.objects.update_or_create(
            matricula=aluno_eduq.matricula,
            defaults={
                "nome": aluno_eduq.nome,
                "celular": aluno_eduq.telefone,
                "turma": turma_local,
                "ativo": aluno_eduq.ativo,
                "origem": OrigemDados.EDUQ,
                "ultima_sincronizacao": agora,
            },
        )
        if criado:
            criados += 1
        else:
            atualizados += 1

    return criados, atualizados, ignorados


def sincronizar_turma_eduq(codigo_turma: str) -> ResultadoSync:
    """Sincroniza uma turma especifica (e seus alunos) com o Eduq.

    Usada quando o operador escolhe uma turma no seletor exibido pela busca
    de aluno sem resultado (o Eduq nao tem busca por nome — so
    ``listar_alunos`` por turma).
    """

    client = EduqClient()
    turmas = [t for t in client.listar_turmas() if t.codigo == str(codigo_turma)]
    if not turmas:
        raise EduqAPIError(f"Turma {codigo_turma} não encontrada no Eduq.")

    turma_eduq = turmas[0]
    turma_local, turma_criada = _upsert_turma(turma_eduq)
    alunos_eduq = client.listar_alunos(turma_eduq.codigo)
    criados, atualizados, ignorados = _upsert_alunos(alunos_eduq, turma_local)

    resultado = _resultado_vazio()
    resultado["turmas_criadas" if turma_criada else "turmas_atualizadas"] = 1
    resultado["alunos_criados"] = criados
    resultado["alunos_atualizados"] = atualizados
    resultado["alunos_ignorados"] = ignorados
    return resultado


def sincronizar_todas_turmas_eduq() -> ResultadoSync:
    """Sincroniza todas as turmas do Eduq e os alunos de cada uma.

    Botão "Sincronizar alunos e turmas" da listagem de Alunos — mesmo conceito
    de ``gestao_cme.views.atualizar_alunos_eduq``, numa tabela própria.
    """

    client = EduqClient()
    resultado = _resultado_vazio()

    for turma_eduq in client.listar_turmas():
        turma_local, turma_criada = _upsert_turma(turma_eduq)
        resultado["turmas_criadas" if turma_criada else "turmas_atualizadas"] += 1

        alunos_eduq = client.listar_alunos(turma_eduq.codigo)
        criados, atualizados, ignorados = _upsert_alunos(alunos_eduq, turma_local)
        resultado["alunos_criados"] += criados
        resultado["alunos_atualizados"] += atualizados
        resultado["alunos_ignorados"] += ignorados

    return resultado


def executar_sync_alunos_e_registrar(
    disparado_por: str = "", tipo: str = "COMPLETA"
) -> object:
    """Executa a sincronização completa de turmas/alunos e registra em RegistroSync.

    Mesmo padrão de ``gestao_lab.services.dental_sync.executar_sync_e_registrar``
    (histórico único, compartilhado entre as duas fontes de dados
    independentes — pacientes via Dental, alunos via Eduq).
    """

    from gestao_lab.models import RegistroSync

    registro = RegistroSync.objects.create(tipo=tipo, disparado_por=disparado_por)
    inicio = time.monotonic()

    try:
        resultado = sincronizar_todas_turmas_eduq()
        registro.alunos_criados = resultado["alunos_criados"]
        registro.alunos_atualizados = resultado["alunos_atualizados"]
        registro.sucesso = True
    except Exception as exc:
        registro.erro = str(exc)
        registro.sucesso = False
        raise
    finally:
        registro.duracao_segundos = round(time.monotonic() - inicio, 2)
        registro.save()

    return registro
