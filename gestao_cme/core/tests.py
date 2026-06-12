from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.integrations.eduq import AlunoEduq, TurmaEduq
from core.models import Aluno, Turma
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
        aluno = Aluno.objects.select_related("turma").get(matricula="20260001")
        self.assertEqual(aluno.nome, "Ana Clara Ribeiro")
        self.assertEqual(aluno.telefone, "(62) 99901-0001")
        self.assertEqual(aluno.turma.codigo, "50057")

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
