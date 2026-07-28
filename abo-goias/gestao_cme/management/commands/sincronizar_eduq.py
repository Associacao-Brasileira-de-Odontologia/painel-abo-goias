from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from gestao_cme.integrations.eduq import EduqAPIError, EduqClient
from gestao_cme.services.eduq_sync import SyncResumo, sincronizar_eduq


class Command(BaseCommand):
    help = "Consulta a API do Eduq e sincroniza turmas e alunos no banco local."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa a sincronizacao e desfaz as gravacoes ao final.",
        )
        parser.add_argument(
            "--somente-turmas",
            action="store_true",
            help="Sincroniza apenas turmas.",
        )
        parser.add_argument(
            "--somente-alunos",
            action="store_true",
            help="Sincroniza apenas alunos.",
        )
        parser.add_argument(
            "--turma-codigo",
            action="append",
            default=[],
            help=(
                "Codigo Eduq de uma turma para sincronizar alunos. "
                "Pode ser usado mais de uma vez."
            ),
        )
        parser.add_argument(
            "--intervalo-consultas",
            type=float,
            default=0,
            help="Segundos de espera entre consultas de alunos por turma.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["somente_turmas"] and options["somente_alunos"]:
            raise CommandError(
                "Use apenas uma opcao entre --somente-turmas e --somente-alunos."
            )

        sincronizar_turmas = not options["somente_alunos"]
        sincronizar_alunos = not options["somente_turmas"]
        turma_codigos = options["turma_codigo"]
        intervalo_consultas = options["intervalo_consultas"]

        try:
            with transaction.atomic():
                resultado = sincronizar_eduq(
                    client=EduqClient(),
                    sincronizar_turmas=sincronizar_turmas,
                    sincronizar_alunos=sincronizar_alunos,
                    turma_codigos=turma_codigos,
                    intervalo_consultas=intervalo_consultas,
                )
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except EduqAPIError as exc:
            raise CommandError(str(exc)) from exc

        self._escrever_resumo("Turmas", resultado.turmas)
        self._escrever_resumo("Alunos", resultado.alunos)

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("Dry-run concluido. Nenhuma alteracao foi salva.")
            )
        elif resultado.turmas.erros or resultado.alunos.erros:
            self.stdout.write(
                self.style.WARNING("Sincronizacao concluida com alertas.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Sincronizacao concluida com sucesso.")
            )

    def _escrever_resumo(self, titulo: str, resumo: SyncResumo) -> None:
        self.stdout.write(
            f"{titulo}: {resumo.criados} criados, "
            f"{resumo.atualizados} atualizados, {len(resumo.erros)} erros."
        )
        for erro in resumo.erros:
            self.stdout.write(self.style.WARNING(f" - {erro}"))
