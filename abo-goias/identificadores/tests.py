"""Testes da aplicacao de identificadores."""

from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestao_cme.models import Aluno, OrigemDados, Turma


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


@override_settings(ALLOWED_HOSTS=["testserver"])
class IdentificadoresBuscaTurmaTests(TestCase):
    """Cobre a busca de turma, o filtro ativa/finalizada, o painel de
    contagens e a listagem de alunos por turma (Fase 3.1)."""

    def setUp(self) -> None:
        self.hoje = timezone.localdate()
        self.usuario = get_user_model().objects.create_user(
            username="identificadores-3-1", password="senha-segura"
        )
        self.client.force_login(self.usuario)

        self.turma_ativa = Turma.objects.create(
            nome="Ortodontia Ativa", codigo="ATV-1",
            data_fim=self.hoje + timedelta(days=30), origem=OrigemDados.EDUQ,
        )
        self.turma_sem_data = Turma.objects.create(
            nome="Endodontia Sem Data", codigo="SEM-1", origem=OrigemDados.EDUQ,
        )
        self.turma_finalizada = Turma.objects.create(
            nome="Periodontia Finalizada", codigo="FIN-1",
            data_fim=self.hoje - timedelta(days=30), origem=OrigemDados.EDUQ,
        )
        Aluno.objects.create(
            nome="Ana Souza", matricula="M1", turma=self.turma_ativa,
            cidade="Goiânia", uf="GO", origem=OrigemDados.EDUQ,
        )
        Aluno.objects.create(
            nome="Bruno Lima", matricula="M2", turma=self.turma_ativa,
            origem=OrigemDados.EDUQ,
        )

    def test_painel_mostra_contagens_de_situacao_e_alunos(self) -> None:
        response = self.client.get(reverse("identificadores:index"))

        self.assertEqual(response.context["total_turmas"], 3)
        self.assertEqual(response.context["ativas_count"], 2)
        self.assertEqual(response.context["finalizadas_count"], 1)
        self.assertEqual(response.context["total_alunos_sinc"], 2)

    def test_buscar_turmas_filtra_por_situacao_ativas(self) -> None:
        response = self.client.get(
            reverse("identificadores:buscar_turmas"), {"status": "ativas"}
        )

        self.assertContains(response, "ATV-1")
        self.assertContains(response, "SEM-1")
        self.assertNotContains(response, "FIN-1")

    def test_buscar_turmas_filtra_finalizadas(self) -> None:
        response = self.client.get(
            reverse("identificadores:buscar_turmas"), {"status": "finalizadas"}
        )

        self.assertContains(response, "FIN-1")
        self.assertNotContains(response, "ATV-1")

    def test_buscar_turmas_filtra_por_texto(self) -> None:
        response = self.client.get(
            reverse("identificadores:buscar_turmas"),
            {"q": "Endodontia", "status": "todas"},
        )

        self.assertContains(response, "SEM-1")
        self.assertNotContains(response, "ATV-1")

    def test_turma_alunos_lista_alunos_e_campo_oculto(self) -> None:
        response = self.client.get(
            reverse("identificadores:turma_alunos", args=[self.turma_ativa.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ana Souza")
        self.assertContains(response, "Bruno Lima")
        self.assertContains(response, f'name="turma" value="{self.turma_ativa.pk}"')
        self.assertContains(response, "Ativa")

    def test_turma_alunos_marca_turma_finalizada(self) -> None:
        response = self.client.get(
            reverse("identificadores:turma_alunos", args=[self.turma_finalizada.pk])
        )

        self.assertContains(response, "Finalizada")
