from __future__ import annotations

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_ativo(context, url_name: str, match: str = "") -> str:
    """Retorna "active" quando a rota atual corresponde ao item de navegação.

    A rota atual é lida de ``request.resolver_match.view_name`` (inclui o
    namespace do app, se houver), então nenhuma view precisa mais passar
    ``active_page`` no contexto nem cada template precisar redeclarar qual
    item deve ficar destacado. ``match`` aceita nomes de rota adicionais
    (separados por espaço) que também devem ativar o item — usado quando uma
    tela "filha" (ex.: editar um registro) deve manter destacado o item da
    lista correspondente.
    """
    request = context.get("request")
    resolver_match = getattr(request, "resolver_match", None)
    atual = getattr(resolver_match, "view_name", None)
    if atual is None:
        return ""
    nomes = {url_name, *match.split()}
    return "active" if atual in nomes else ""
