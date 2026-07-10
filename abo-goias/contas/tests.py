from unittest.mock import patch

from contas.admin import SolicitacaoCadastroAdmin
from contas.forms import SolicitacaoCadastroForm
from contas.models import SolicitacaoCadastro
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
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


def _dados_solicitacao(**kwargs) -> dict:
    base = {
        "nome_completo": "Fulano de Tal",
        "email": "fulano@example.com",
        "username": "fulano",
        "cargo": "Recepção",
        "justificativa": "Preciso acessar o painel.",
    }
    base.update(kwargs)
    return base


@override_settings(ALLOWED_HOSTS=["testserver"])
class SolicitarAcessoViewTests(TestCase):
    def test_get_exibe_formulario(self) -> None:
        response = self.client.get(reverse("solicitar_acesso"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/solicitar_acesso.html")

    def test_usuario_autenticado_e_redirecionado_ao_portal(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="ja-logado", password="senha-segura"
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("solicitar_acesso"))

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_post_valido_cria_solicitacao_pendente_e_redireciona(self) -> None:
        response = self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        self.assertRedirects(
            response,
            reverse("solicitar_acesso_enviado"),
            fetch_redirect_response=False,
        )
        solicitacao = SolicitacaoCadastro.objects.get(username="fulano")
        self.assertEqual(solicitacao.status, SolicitacaoCadastro.Status.PENDENTE)
        self.assertEqual(solicitacao.nome_completo, "Fulano de Tal")

    def test_post_nao_cria_usuario_de_imediato(self) -> None:
        self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        self.assertFalse(get_user_model().objects.filter(username="fulano").exists())

    def test_link_para_solicitar_acesso_aparece_no_login(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertContains(response, reverse("solicitar_acesso"))

    @override_settings(ADMINS=[("Admin", "admin@example.com")])
    def test_post_valido_notifica_admin_configurado(self) -> None:
        self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("admin@example.com", mail.outbox[0].to)
        self.assertIn("Fulano de Tal", mail.outbox[0].body)
        self.assertIn("fulano", mail.outbox[0].body)

    @override_settings(ADMINS=[])
    def test_post_sem_admin_configurado_nao_envia_email(self) -> None:
        self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ADMINS=[("Admin", "admin@example.com")])
    def test_email_ao_admin_contem_link_de_revisao(self) -> None:
        self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        solicitacao = SolicitacaoCadastro.objects.get(username="fulano")
        self.assertIn(
            f"/admin/contas/solicitacaocadastro/{solicitacao.pk}/change/",
            mail.outbox[0].body,
        )

    @override_settings(ADMINS=[("Admin", "admin@example.com")])
    @patch("contas.emails.send_mail", side_effect=RuntimeError("SMTP fora do ar"))
    def test_falha_ao_notificar_admin_nao_impede_solicitacao(
        self, mock_send_mail
    ) -> None:
        """Uma falha de e-mail (ex.: SMTP mal configurado) não pode quebrar
        a tela pública de solicitação de acesso — o pedido já foi salvo
        antes da tentativa de notificação."""

        response = self.client.post(reverse("solicitar_acesso"), _dados_solicitacao())

        self.assertRedirects(
            response,
            reverse("solicitar_acesso_enviado"),
            fetch_redirect_response=False,
        )
        self.assertTrue(SolicitacaoCadastro.objects.filter(username="fulano").exists())


class SolicitacaoCadastroFormTests(TestCase):
    def test_valido_com_dados_completos(self) -> None:
        form = SolicitacaoCadastroForm(data=_dados_solicitacao())

        self.assertTrue(form.is_valid(), form.errors)

    def test_username_ja_existente_como_usuario_e_rejeitado(self) -> None:
        get_user_model().objects.create_user(username="fulano", password="senha-segura")

        form = SolicitacaoCadastroForm(data=_dados_solicitacao())

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_username_com_solicitacao_pendente_e_rejeitado(self) -> None:
        SolicitacaoCadastro.objects.create(
            nome_completo="Outro", email="outro@example.com", username="fulano"
        )

        form = SolicitacaoCadastroForm(data=_dados_solicitacao())

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_email_ja_existente_como_usuario_e_rejeitado(self) -> None:
        get_user_model().objects.create_user(
            username="outro", password="senha-segura", email="fulano@example.com"
        )

        form = SolicitacaoCadastroForm(data=_dados_solicitacao())

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_cargo_e_justificativa_sao_opcionais(self) -> None:
        form = SolicitacaoCadastroForm(
            data=_dados_solicitacao(cargo="", justificativa="")
        )

        self.assertTrue(form.is_valid(), form.errors)


class SolicitacaoCadastroModelTests(TestCase):
    def test_aprovar_cria_usuario_ativo_e_marca_status(self) -> None:
        revisor = get_user_model().objects.create_user(
            username="admin", password="senha-segura"
        )
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva Souza",
            email="maria@example.com",
            username="maria",
        )

        usuario = solicitacao.aprovar(revisor=revisor)

        self.assertIsNotNone(usuario)
        self.assertTrue(usuario.is_active)
        self.assertEqual(usuario.username, "maria")
        self.assertEqual(usuario.email, "maria@example.com")
        self.assertEqual(usuario.first_name, "Maria")
        self.assertEqual(usuario.last_name, "Silva Souza")
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, SolicitacaoCadastro.Status.APROVADA)
        self.assertEqual(solicitacao.usuario_criado, usuario)
        self.assertEqual(solicitacao.revisado_por, revisor)
        self.assertIsNotNone(solicitacao.revisado_em)

    def test_aprovar_solicitacao_nao_pendente_e_ignorada(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria",
            email="maria@example.com",
            username="maria",
            status=SolicitacaoCadastro.Status.REJEITADA,
        )

        self.assertIsNone(solicitacao.aprovar())
        self.assertFalse(get_user_model().objects.filter(username="maria").exists())

    def test_rejeitar_marca_status_sem_criar_usuario(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria", email="maria@example.com", username="maria"
        )

        self.assertTrue(solicitacao.rejeitar(observacao="Fora do escopo."))
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, SolicitacaoCadastro.Status.REJEITADA)
        self.assertEqual(solicitacao.observacao_revisao, "Fora do escopo.")
        self.assertFalse(get_user_model().objects.filter(username="maria").exists())


@override_settings(ALLOWED_HOSTS=["testserver"])
class SolicitacaoCadastroAdminActionTests(TestCase):
    def setUp(self) -> None:
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="senha-segura"
        )
        self.model_admin = SolicitacaoCadastroAdmin(SolicitacaoCadastro, site)

    def _request(self):
        request = RequestFactory().post("/admin/")
        request.user = self.admin_user
        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_acao_aprovar_cria_usuario_e_envia_email(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva",
            email="maria@example.com",
            username="maria",
        )

        self.model_admin.aprovar_solicitacoes(
            self._request(), SolicitacaoCadastro.objects.filter(pk=solicitacao.pk)
        )

        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, SolicitacaoCadastro.Status.APROVADA)
        self.assertTrue(
            get_user_model().objects.filter(username="maria", is_active=True).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("maria@example.com", mail.outbox[0].to)

    def test_acao_rejeitar_marca_status_e_nao_cria_usuario(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva",
            email="maria@example.com",
            username="maria",
        )

        self.model_admin.rejeitar_solicitacoes(
            self._request(), SolicitacaoCadastro.objects.filter(pk=solicitacao.pk)
        )

        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, SolicitacaoCadastro.Status.REJEITADA)
        self.assertFalse(get_user_model().objects.filter(username="maria").exists())

    def test_acao_rejeitar_avisa_por_email_quem_solicitou(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva",
            email="maria@example.com",
            username="maria",
        )

        self.model_admin.rejeitar_solicitacoes(
            self._request(), SolicitacaoCadastro.objects.filter(pk=solicitacao.pk)
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("maria@example.com", mail.outbox[0].to)

    def test_email_de_rejeicao_inclui_observacao_quando_houver(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva",
            email="maria@example.com",
            username="maria",
            observacao_revisao="Fora do escopo da instituição.",
        )

        self.model_admin.rejeitar_solicitacoes(
            self._request(), SolicitacaoCadastro.objects.filter(pk=solicitacao.pk)
        )

        self.assertIn("Fora do escopo da instituição.", mail.outbox[0].body)

    def test_rejeitar_solicitacao_ja_revisada_nao_reenvia_email(self) -> None:
        solicitacao = SolicitacaoCadastro.objects.create(
            nome_completo="Maria Silva",
            email="maria@example.com",
            username="maria",
            status=SolicitacaoCadastro.Status.REJEITADA,
        )

        self.model_admin.rejeitar_solicitacoes(
            self._request(), SolicitacaoCadastro.objects.filter(pk=solicitacao.pk)
        )

        self.assertEqual(len(mail.outbox), 0)
