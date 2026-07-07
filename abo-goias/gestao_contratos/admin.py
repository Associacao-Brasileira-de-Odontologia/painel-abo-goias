"""Administração da app de gestão de contratos.

Só o cadastro de terminais de assinatura é exposto aqui — contratos e
sessões já têm telas dedicadas próprias e não precisam do Django Admin.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from .models import TerminalAssinatura


@admin.register(TerminalAssinatura)
class TerminalAssinaturaAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativo", "link_terminal", "criado_em")
    list_filter = ("ativo",)
    search_fields = ("nome",)
    readonly_fields = ("token", "link_terminal")
    fields = ("nome", "ativo", "token", "link_terminal")

    @admin.display(description="Link do terminal")
    def link_terminal(self, obj: TerminalAssinatura) -> str:
        if not obj.pk:
            return "—"
        from django.urls import reverse

        url = reverse("terminal_assinatura", args=[obj.token])
        return format_html('<a href="{0}" target="_blank">{0}</a>', url)
