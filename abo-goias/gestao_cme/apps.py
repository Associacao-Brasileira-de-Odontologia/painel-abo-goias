from django.apps import AppConfig


class GestaoCmeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestao_cme"
    label = "core"
    verbose_name = "Gestão de CME"

    def ready(self) -> None:
        """Inscreve a contribuição desta app no Portal (ver comum.portal).

        O import mora aqui dentro de propósito: `ready()` roda depois que o
        registry de apps está pronto, e importar models no topo de apps.py
        levanta AppRegistryNotReady.
        """

        from comum.portal import registrar

        from .services.portal import FONTE

        registrar(FONTE)
