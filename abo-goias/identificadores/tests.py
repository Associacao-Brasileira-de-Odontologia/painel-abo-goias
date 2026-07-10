"""Testes da aplicacao de identificadores."""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class IdentificadoresModelTests(SimpleTestCase):
    def test_app_nao_define_models_persistidos_proprios(self) -> None:
        app_config = apps.get_app_config("identificadores")

        self.assertEqual(list(app_config.get_models()), [])


@override_settings(ALLOWED_HOSTS=["testserver"])
class IdentificadoresRotaTests(TestCase):
    """Identificadores e um app Django independente, montado em
    /identificadores/ (ver abo_goias/urls.py). Estes testes cobrem o
    essencial da rota; os testes de geracao de PPTX ficam nos servicos."""

    def test_anonimo_redireciona_para_login(self) -> None:
        response = self.client.get(reverse("identificadores:index"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("identificadores:index")}',
            fetch_redirect_response=False,
        )

    def test_usuario_logado_ve_tela_de_identificadores(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="identificadores-teste", password="senha-segura"
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("identificadores:index"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "identificadores/index.html")
