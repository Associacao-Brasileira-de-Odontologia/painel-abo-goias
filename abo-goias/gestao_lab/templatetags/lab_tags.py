import re
from urllib.parse import quote

from django import template

register = template.Library()


@register.filter
def whatsapp_url(numero: str) -> str:
    """Converte um numero de telefone em URL de abertura do WhatsApp Web."""
    numero_limpo = re.sub(r"\D", "", str(numero or ""))
    if not numero_limpo:
        return "#"
    if not numero_limpo.startswith("55"):
        numero_limpo = "55" + numero_limpo
    return f"https://wa.me/{numero_limpo}"


@register.filter
def whatsapp_url_msg(numero: str, mensagem: str) -> str:
    """Converte numero e mensagem em URL do WhatsApp com texto pre-preenchido."""
    numero_limpo = re.sub(r"\D", "", str(numero or ""))
    if not numero_limpo:
        return "#"
    if not numero_limpo.startswith("55"):
        numero_limpo = "55" + numero_limpo
    return f"https://wa.me/{numero_limpo}?text={quote(str(mensagem))}"


@register.simple_tag
def status_badge_class(status: str) -> str:
    """Retorna a classe CSS do badge conforme o status do pedido."""
    mapa = {
        "EM_DIA": "badge-em-dia",
        "A_CONFIRMAR": "badge-a-confirmar",
        "ATRASADO": "badge-atrasado",
        "CONCLUIDO": "badge-neutro",
    }
    return mapa.get(status, "")
