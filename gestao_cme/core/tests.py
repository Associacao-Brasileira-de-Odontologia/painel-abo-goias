from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver"])
class RotasIniciaisTests(TestCase):
    def test_home_sem_login_redireciona_para_login(self):
        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("home")}',
            fetch_redirect_response=False,
        )

    def test_login_e_a_tela_inicial_para_usuario_nao_autenticado(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/auth/login.html")

    def test_catalog_legado_redireciona_para_home(self):
        response = self.client.get("/catalog/")

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_home_autenticada_carrega_painel(self):
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
