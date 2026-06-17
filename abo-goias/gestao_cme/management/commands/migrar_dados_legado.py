from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gestao_cme.services.migracao_legado import migrar_dados_legado


class Command(BaseCommand):
    help = "Migra para o banco Django os dados do sistema legado mantido em planilhas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--diretorio",
            default=str(Path.home() / "Downloads"),
            help="Diretorio contendo os arquivos exportados do sistema legado.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa a migracao e desfaz as gravacoes ao final.",
        )

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                resultado = migrar_dados_legado(Path(options["diretorio"]))
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._escrever_resumo("Abrigos", resultado.abrigos)
        self._escrever_resumo("Kits", resultado.kits)
        self._escrever_resumo("Materiais", resultado.materiais)
        self._escrever_resumo("Movimentacoes", resultado.movimentacoes)

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("Dry-run concluido. Nenhuma alteracao foi salva.")
            )
        elif _tem_erros(resultado):
            self.stdout.write(self.style.WARNING("Migracao concluida com alertas."))
        else:
            self.stdout.write(self.style.SUCCESS("Migracao concluida com sucesso."))

    def _escrever_resumo(self, titulo, resumo):
        self.stdout.write(
            f"{titulo}: {resumo.criados} criados, "
            f"{resumo.atualizados} atualizados, {len(resumo.erros)} erros."
        )
        for erro in resumo.erros[:20]:
            self.stdout.write(self.style.WARNING(f" - {erro}"))
        if len(resumo.erros) > 20:
            self.stdout.write(
                self.style.WARNING(f" - ... mais {len(resumo.erros) - 20} erro(s).")
            )


def _tem_erros(resultado):
    return any(
        (
            resultado.abrigos.erros,
            resultado.kits.erros,
            resultado.materiais.erros,
            resultado.movimentacoes.erros,
        )
    )
