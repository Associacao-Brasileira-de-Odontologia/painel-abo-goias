"""Management command para sincronizar pacientes do Dental Office.

Só pacientes — alunos vêm do Eduq (ver ``sincronizar_eduq_lab``), num fluxo
independente desde a correção que trocou a fonte de dados de AlunoLab do
Dental Office (que nunca teve informação real de alunos) para o Eduq.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from gestao_lab.integrations.dental import DentalAPIError
from gestao_lab.models import RegistroSync
from gestao_lab.services.dental_sync import sincronizar_pacientes


class Command(BaseCommand):
    help = "Sincroniza pacientes do Dental Office com o banco local."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clinic-id",
            type=int,
            default=None,
            help="ID da clínica no Dental Office (padrão: DENTAL_CLINIC_ID).",
        )

    def handle(self, *args, **options):
        clinic_id = options["clinic_id"] or getattr(settings, "DENTAL_CLINIC_ID", None)

        registro = RegistroSync.objects.create(
            tipo=RegistroSync.Tipo.COMPLETA,
            disparado_por="manage.py",
        )
        inicio = time.monotonic()
        sucesso = True

        try:
            if not clinic_id:
                self.stderr.write(
                    self.style.ERROR(
                        "Informe --clinic-id ou configure DENTAL_CLINIC_ID."
                    )
                )
                registro.erro = "DENTAL_CLINIC_ID não configurado."
                registro.sucesso = False
                registro.save()
                return

            self.stdout.write(f"Sincronizando pacientes (clínica {clinic_id})...")
            rp = sincronizar_pacientes(clinic_id=clinic_id)
            registro.pacientes_criados = rp["criados"]
            registro.pacientes_atualizados = rp["atualizados"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Pacientes — criados: {rp['criados']}, "
                    f"atualizados: {rp['atualizados']}, "
                    f"ignorados: {rp['ignorados']}."
                )
            )

        except DentalAPIError as exc:
            self.stderr.write(self.style.ERROR(f"Erro na API Dental Office: {exc}"))
            registro.erro = str(exc)
            sucesso = False
        finally:
            registro.sucesso = sucesso
            registro.duracao_segundos = round(time.monotonic() - inicio, 2)
            registro.save()
