"""Testes da aplicacao de identificadores."""

from django.apps import apps
from django.test import SimpleTestCase


class IdentificadoresModelTests(SimpleTestCase):
    def test_app_nao_define_models_persistidos_proprios(self) -> None:
        app_config = apps.get_app_config("identificadores")

        self.assertEqual(list(app_config.get_models()), [])
