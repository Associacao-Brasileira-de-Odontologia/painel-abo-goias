from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver"])
class PasswordChangeViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="troca-senha", password="senha-antiga-123"
        )

    def test_anonimo_redireciona_para_login(self) -> None:
        response = self.client.get(reverse("password_change"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("password_change")}',
            fetch_redirect_response=False,
        )

    def test_usuario_logado_ve_formulario(self) -> None:
        self.client.force_login(self.usuario)

        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/password_change_form.html")

    def test_troca_de_senha_com_sucesso_redireciona_para_concluido(self) -> None:
        self.client.force_login(self.usuario)

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "senha-antiga-123",
                "new_password1": "senha-nova-456",
                "new_password2": "senha-nova-456",
            },
        )

        self.assertRedirects(
            response, reverse("password_change_done"), fetch_redirect_response=False
        )
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("senha-nova-456"))

    def test_senha_atual_incorreta_nao_altera_senha(self) -> None:
        self.client.force_login(self.usuario)

        self.client.post(
            reverse("password_change"),
            {
                "old_password": "senha-errada",
                "new_password1": "senha-nova-456",
                "new_password2": "senha-nova-456",
            },
        )

        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("senha-antiga-123"))


class PerfilViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="perfil-teste",
            password="senha-segura",
            first_name="Maria",
            email="maria@example.com",
        )

    def test_anonimo_redireciona_para_login(self) -> None:
        response = self.client.get(reverse("perfil"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("perfil")}',
            fetch_redirect_response=False,
        )

    def test_usuario_logado_ve_dados_da_conta(self) -> None:
        self.client.force_login(self.usuario)

        response = self.client.get(reverse("perfil"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/perfil.html")
        self.assertContains(response, "Maria")
        self.assertContains(response, "maria@example.com")
