from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from gestao_cme.permissoes import GRUPOS_PADRAO


class Command(BaseCommand):
    help = (
        "Cria os grupos de acesso padrao (recepcao, "
        "coordenacao, gestao), caso ainda nao existam."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        for nome in GRUPOS_PADRAO:
            _, criado = Group.objects.get_or_create(name=nome)
            if criado:
                self.stdout.write(self.style.SUCCESS(f"Grupo '{nome}' criado."))
            else:
                self.stdout.write(f"Grupo '{nome}' ja existia.")
