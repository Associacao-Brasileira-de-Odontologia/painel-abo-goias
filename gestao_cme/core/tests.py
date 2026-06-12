import json
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.integrations.eduq import AlunoEduq, EduqAPIError, TurmaEduq
from core.models import Aluno, Armario, Material, OrigemDados, Turma
from core.services.eduq_sync import sincronizar_alunos_eduq, sincronizar_eduq, sincronizar_turmas_eduq


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

    def test_listagem_de_alunos_nao_exibe_academicos_de_exemplo(self):
        turma_exemplo = Turma.objects.create(
            codigo="T-EXEMPLO",
            nome="Turma Exemplo",
            origem=OrigemDados.EXEMPLO,
        )
        turma_eduq = Turma.objects.create(
            codigo="T-EDUQ",
            nome="Turma Eduq",
            origem=OrigemDados.EDUQ,
        )
        Aluno.objects.create(
            matricula="A-EXEMPLO",
            nome="Aluno Exemplo",
            turma=turma_exemplo,
            origem=OrigemDados.EXEMPLO,
        )
        Aluno.objects.create(
            matricula="A-EDUQ",
            nome="Aluno Eduq",
            turma=turma_eduq,
            origem=OrigemDados.EDUQ,
        )
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_superuser=True,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("alunos_por_turma"))

        self.assertContains(response, "Aluno Eduq")
        self.assertNotContains(response, "Aluno Exemplo")

    def test_botao_de_sincronizacao_aparece_na_tela_de_alunos_por_turma(self):
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_staff=True,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("alunos_por_turma"))

        self.assertContains(response, "Sincronizar turmas")
        self.assertContains(response, reverse("sincronizar_turmas_eduq"))

    @patch("core.views.sincronizar_eduq")
    def test_botao_sincroniza_turmas_sem_sincronizar_alunos(self, sync_mock):
        sync_mock.return_value = SimpleNamespace(
            turmas=SimpleNamespace(criados=2, atualizados=3, erros=[]),
        )
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_staff=True,
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"), follow=True)

        sync_mock.assert_called_once_with(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
        self.assertRedirects(response, reverse("alunos_por_turma"))
        self.assertContains(response, "Turmas sincronizadas: 2 criadas, 3 atualizadas")

    @patch("core.views.sincronizar_eduq")
    def test_sincronizacao_de_turmas_exibe_erro_da_api(self, sync_mock):
        sync_mock.side_effect = EduqAPIError("API indisponivel")
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_staff=True,
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"), follow=True)

        self.assertContains(response, "Nao foi possivel sincronizar turmas")
        self.assertContains(response, "API indisponivel")

    @patch("core.views.sincronizar_eduq")
    def test_sincronizacao_de_turmas_exige_usuario_staff(self, sync_mock):
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_staff=False,
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"))

        self.assertEqual(response.status_code, 403)
        sync_mock.assert_not_called()


class EduqSyncTests(TestCase):
    def test_sincroniza_turmas_e_alunos_do_payload_eduq(self):
        turmas = [
            {
                "Identificador da Turma": 50057,
                "Sigla": "END-2026-1",
                "Descrição": "Especializacao em Endodontia",
                "TurmaId": 123,
                "Matrículas Ativas": 11,
                "Data de Início": "06/03/2026",
                "Data de Finalização": "27/11/2027",
            }
        ]
        alunos = [
            {
                "Id": 20260001,
                "Identificador": "A-20260001",
                "Nome": "Ana Clara Ribeiro",
                "CPF": "101.222.333-44",
                "CelularSMS": "(62) 99901-0001",
                "Email": "ana.ribeiro@example.com",
                "Descricao": "Especializacao em Endodontia",
                "UF": "GO",
                "codigoTurma": "50057",
            }
        ]

        resumo_turmas = sincronizar_turmas_eduq(turmas)
        resumo_alunos = sincronizar_alunos_eduq(alunos)

        self.assertEqual(resumo_turmas.criados, 1)
        self.assertEqual(resumo_alunos.criados, 1)
        turma = Turma.objects.get(codigo="50057")
        self.assertEqual(turma.nome, "END-2026-1 - Especializacao em Endodontia")
        self.assertEqual(turma.curso, "Especializacao em Endodontia")
        self.assertEqual(turma.data_inicio.isoformat(), "2026-03-06")
        self.assertEqual(turma.data_fim.isoformat(), "2027-11-27")
        self.assertEqual(turma.observacoes, "Matriculas ativas no Eduq: 11")
        self.assertEqual(turma.origem, OrigemDados.EDUQ)
        self.assertIsNotNone(turma.ultima_sincronizacao)
        aluno = Aluno.objects.select_related("turma").get(matricula="20260001")
        self.assertEqual(aluno.nome, "Ana Clara Ribeiro")
        self.assertEqual(aluno.telefone, "(62) 99901-0001")
        self.assertEqual(aluno.turma.codigo, "50057")
        self.assertEqual(aluno.origem, OrigemDados.EDUQ)
        self.assertIsNotNone(aluno.ultima_sincronizacao)

    def test_sincronizacao_e_idempotente_por_codigo_e_matricula(self):
        sincronizar_turmas_eduq([{"codigo": "IMP-2026-1", "nome": "Implantodontia"}])
        sincronizar_alunos_eduq(
            [{"matricula": "20260002", "nome": "Bruno Almeida", "codigoTurma": "IMP-2026-1"}]
        )

        resumo_turmas = sincronizar_turmas_eduq(
            [{"codigo": "IMP-2026-1", "nome": "Implantodontia Atualizada"}]
        )
        resumo_alunos = sincronizar_alunos_eduq(
            [
                {
                    "matricula": "20260002",
                    "nome": "Bruno Henrique Almeida",
                    "codigoTurma": "IMP-2026-1",
                }
            ]
        )

        self.assertEqual(resumo_turmas.atualizados, 1)
        self.assertEqual(resumo_alunos.atualizados, 1)
        self.assertEqual(Turma.objects.count(), 1)
        self.assertEqual(Aluno.objects.count(), 1)
        self.assertEqual(Turma.objects.get().nome, "Implantodontia Atualizada")
        self.assertEqual(Aluno.objects.get().nome, "Bruno Henrique Almeida")

    def test_aluno_com_turma_inexistente_retorna_erro_sem_criar_registro(self):
        resumo = sincronizar_alunos_eduq(
            [{"matricula": "20260003", "nome": "Carolina Sousa", "codigoTurma": "TURMA-X"}]
        )

        self.assertEqual(resumo.criados, 0)
        self.assertEqual(len(resumo.erros), 1)
        self.assertFalse(Aluno.objects.exists())

    def test_sincronizacao_permite_cpfs_duplicados_quando_ids_eduq_sao_diferentes(self):
        Turma.objects.create(codigo="TURMA-CPF", nome="Turma CPF", origem=OrigemDados.EDUQ)

        resumo = sincronizar_alunos_eduq(
            [
                {
                    "Id": 1001,
                    "Nome": "Aluno Um",
                    "CPF": "111.222.333-44",
                    "codigoTurma": "TURMA-CPF",
                },
                {
                    "Id": 1002,
                    "Nome": "Aluno Dois",
                    "CPF": "111.222.333-44",
                    "codigoTurma": "TURMA-CPF",
                },
            ]
        )

        self.assertEqual(resumo.criados, 2)
        self.assertEqual(Aluno.objects.filter(cpf="111.222.333-44").count(), 2)

    def test_sincronizacao_consulta_alunos_por_turma_eduq(self):
        class FakeEduqClient:
            codigos_consultados = []

            def listar_turmas(self):
                return [
                    TurmaEduq(codigo="TURMA-1", nome="Turma 1"),
                    TurmaEduq(codigo="TURMA-2", nome="Turma 2"),
                ]

            def listar_alunos(self, codigo_turma_eduq):
                self.codigos_consultados.append(codigo_turma_eduq)
                return [
                    AlunoEduq(
                        matricula=f"ALUNO-{codigo_turma_eduq}",
                        nome=f"Aluno {codigo_turma_eduq}",
                        turma_codigo=codigo_turma_eduq,
                    )
                ]

        client = FakeEduqClient()

        resultado = sincronizar_eduq(client=client)

        self.assertEqual(client.codigos_consultados, ["TURMA-1", "TURMA-2"])
        self.assertEqual(resultado.turmas.criados, 2)
        self.assertEqual(resultado.alunos.criados, 2)
        self.assertEqual(Turma.objects.count(), 2)
        self.assertEqual(Aluno.objects.count(), 2)

    def test_sincronizacao_de_alunos_continua_quando_uma_turma_falha(self):
        class FakeEduqClient:
            def listar_turmas(self):
                return [
                    TurmaEduq(codigo="TURMA-OK", nome="Turma OK"),
                    TurmaEduq(codigo="TURMA-ERRO", nome="Turma Erro"),
                ]

            def listar_alunos(self, codigo_turma_eduq):
                if codigo_turma_eduq == "TURMA-ERRO":
                    raise EduqAPIError("falha temporaria")
                return [
                    AlunoEduq(
                        matricula="ALUNO-OK",
                        nome="Aluno OK",
                        turma_codigo=codigo_turma_eduq,
                    )
                ]

        resultado = sincronizar_eduq(client=FakeEduqClient())

        self.assertEqual(resultado.alunos.criados, 1)
        self.assertEqual(len(resultado.alunos.erros), 1)
        self.assertIn("TURMA-ERRO", resultado.alunos.erros[0])
        self.assertTrue(Aluno.objects.filter(matricula="ALUNO-OK").exists())

    def test_sincronizacao_de_alunos_em_massa_ignora_turmas_de_exemplo(self):
        Turma.objects.create(codigo="TURMA-EDUQ", nome="Turma Eduq", origem=OrigemDados.EDUQ)
        Turma.objects.create(
            codigo="TURMA-EXEMPLO",
            nome="Turma Exemplo",
            origem=OrigemDados.EXEMPLO,
        )

        class FakeEduqClient:
            codigos_consultados = []

            def listar_turmas(self):
                raise AssertionError("Nao deve consultar turmas quando somente alunos.")

            def listar_alunos(self, codigo_turma_eduq):
                self.codigos_consultados.append(codigo_turma_eduq)
                return [
                    AlunoEduq(
                        matricula="ALUNO-EDUQ",
                        nome="Aluno Eduq",
                        turma_codigo=codigo_turma_eduq,
                    )
                ]

        client = FakeEduqClient()

        resultado = sincronizar_eduq(
            client=client,
            sincronizar_turmas=False,
            sincronizar_alunos=True,
        )

        self.assertEqual(client.codigos_consultados, ["TURMA-EDUQ"])
        self.assertEqual(resultado.alunos.criados, 1)


class DadosExemploTests(TestCase):
    def test_fixture_de_exemplo_nao_cria_dados_academicos_fake(self):
        fixture_path = settings.BASE_DIR / "core" / "fixtures" / "dados_exemplo.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        modelos = {item["model"] for item in data}

        self.assertNotIn("core.turma", modelos)
        self.assertNotIn("core.aluno", modelos)
        self.assertNotIn("core.emprestimo", modelos)
        self.assertNotIn("core.itememprestimo", modelos)
        self.assertIn("core.material", modelos)
        self.assertIn("core.kit", modelos)
        self.assertIn("core.armario", modelos)

    def test_fixture_de_exemplo_carrega_apenas_dados_operacionais(self):
        call_command("loaddata", "dados_exemplo", verbosity=0)

        self.assertFalse(Turma.objects.exists())
        self.assertFalse(Aluno.objects.exists())
        self.assertTrue(Material.objects.exists())
        self.assertTrue(Armario.objects.exists())
