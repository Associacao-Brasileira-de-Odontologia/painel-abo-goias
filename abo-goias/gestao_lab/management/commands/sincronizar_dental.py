"""Management command para sincronizar alunos e pacientes do Dental Office."""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from gestao_lab.integrations.dental import DentalAPIError
from gestao_lab.models import RegistroSync
from gestao_lab.services.dental_sync import sincronizar_alunos, sincronizar_pacientes


class Command(BaseCommand):
    help = "Sincroniza alunos e pacientes do Dental Office com o banco local."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clinic-id",
            type=int,
            default=None,
            help="ID da clínica no Dental Office (padrão: DENTAL_CLINIC_ID).",
        )
        parser.add_argument(
            "--user-group",
            type=int,
            default=None,
            help="Grupo de usuários alunos (padrão: DENTAL_USER_GROUP_ALUNO).",
        )
        parser.add_argument(
            "--apenas-pacientes",
            action="store_true",
            help="Sincroniza apenas pacientes, ignorando alunos.",
        )
        parser.add_argument(
            "--apenas-alunos",
            action="store_true",
            help="Sincroniza apenas alunos, ignorando pacientes.",
        )

    def handle(self, *args, **options):
        clinic_id = options["clinic_id"] or getattr(settings, "DENTAL_CLINIC_ID", None)
        user_group = options["user_group"] or getattr(
            settings, "DENTAL_USER_GROUP_ALUNO", 8
        )
        apenas_pacientes = options["apenas_pacientes"]
        apenas_alunos = options["apenas_alunos"]

        registro = RegistroSync.objects.create(
            tipo=RegistroSync.Tipo.COMPLETA,
            disparado_por="manage.py",
        )
        inicio = time.monotonic()
        sucesso = True

        try:
            if not apenas_alunos:
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

            if not apenas_pacientes:
                self.stdout.write(f"Sincronizando alunos (grupo {user_group})...")
                ra = sincronizar_alunos(user_group=user_group)
                registro.alunos_criados = ra["criados"]
                registro.alunos_atualizados = ra["atualizados"]
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Alunos — criados: {ra['criados']}, "
                        f"atualizados: {ra['atualizados']}, "
                        f"ignorados: {ra['ignorados']}."
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
