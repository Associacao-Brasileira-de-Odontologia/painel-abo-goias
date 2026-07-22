"""Management command para sincronizar turmas e alunos do laboratório com o Eduq.

Mesmo papel de ``gestao_cme.management.commands.sincronizar_eduq``, mas sobre
a base própria do laboratório (``TurmaLab``/``AlunoLab``).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from gestao_lab.services.eduq_lab_sync import (
    EduqAPIError,
    sincronizar_todas_turmas_eduq,
    sincronizar_turma_eduq,
)


class Command(BaseCommand):
    help = "Consulta a API do Eduq e sincroniza turmas/alunos do laboratório."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa a sincronizacao e desfaz as gravacoes ao final.",
        )
        parser.add_argument(
            "--turma-codigo",
            action="append",
            default=[],
            help=(
                "Codigo Eduq de uma turma para sincronizar (sozinha, com seus "
                "alunos). Pode ser usado mais de uma vez; sem esta opcao, "
                "sincroniza todas as turmas."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        turma_codigos = options["turma_codigo"]

        try:
            with transaction.atomic():
                if turma_codigos:
                    resultado = {
                        "turmas_criadas": 0,
                        "turmas_atualizadas": 0,
                        "alunos_criados": 0,
                        "alunos_atualizados": 0,
                        "alunos_ignorados": 0,
                    }
                    for codigo in turma_codigos:
                        parcial = sincronizar_turma_eduq(codigo)
                        for chave in resultado:
                            resultado[chave] += parcial[chave]
                else:
                    resultado = sincronizar_todas_turmas_eduq()

                if options["dry_run"]:
                    transaction.set_rollback(True)
        except EduqAPIError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        self.stdout.write(
            f"Turmas: {resultado['turmas_criadas']} criadas, "
            f"{resultado['turmas_atualizadas']} atualizadas."
        )
        self.stdout.write(
            f"Alunos: {resultado['alunos_criados']} criados, "
            f"{resultado['alunos_atualizados']} atualizados, "
            f"{resultado['alunos_ignorados']} ignorados."
        )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("Dry-run concluido. Nenhuma alteracao foi salva.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("Sincronizacao concluida."))
