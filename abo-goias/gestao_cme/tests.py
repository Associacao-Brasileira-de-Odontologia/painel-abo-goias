import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestao_cme.integrations.eduq import (
    AlunoEduq,
    ConfigEduq,
    EduqAPIError,
    EduqClient,
    TurmaEduq,
)
from gestao_cme.models import (
    Abrigo,
    Aluno,
    Armario,
    Emprestimo,
    ItemEmprestimo,
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    OrigemDados,
    RegistroAuditoriaMovimentacao,
    Turma,
)
from gestao_cme.permissoes import GRUPO_GESTAO, GRUPOS_PADRAO, requer_grupo
from gestao_cme.services.eduq_sync import (
    sincronizar_alunos_eduq,
    sincronizar_eduq,
    sincronizar_localizacao_alunos_turma,
    sincronizar_turmas_eduq,
)
from gestao_cme.services.migracao_legado import migrar_dados_legado


@override_settings(ALLOWED_HOSTS=["testserver"])
class RotasIniciaisTests(TestCase):
    def test_healthcheck_responde_sem_login(self) -> None:
        response = self.client.get(reverse("healthcheck"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_home_sem_login_redireciona_para_login(self) -> None:
        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("home")}',
            fetch_redirect_response=False,
        )

    def test_login_e_a_tela_inicial_para_usuario_nao_autenticado(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auth/login.html")

    def test_catalog_legado_redireciona_para_home(self) -> None:
        response = self.client.get("/catalog/")

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_home_autenticada_carrega_portal(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_cme/portal.html")

    def test_cme_home_autenticada_carrega_painel(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("cme_home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_cme/home.html")

    def test_home_exibe_movimentacoes_migradas(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.SAIDA,
            aluno_nome="Aluno Legado",
            aluno_codigo_externo="817",
            turma_nome="Turma Legada",
            pacote_codigo="4801",
            retirado=True,
            arquivo_origem="Relatorio.csv",
            row_hash="hash-home-saida",
            origem=OrigemDados.LEGADO,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("cme_home"))

        self.assertContains(response, "Aluno Legado")
        self.assertContains(response, "Turma Legada")
        self.assertContains(response, "4801")
        self.assertContains(response, "Retirado")

    def test_home_filtra_movimentacoes_por_status_e_tipo(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.SAIDA,
            aluno_nome="Aluno Retirado",
            turma_nome="Turma A",
            pacote_codigo="100",
            retirado=True,
            arquivo_origem="Relatorio.csv",
            row_hash="hash-retirado",
            origem=OrigemDados.LEGADO,
        )
        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno_nome="Aluno Pendente",
            turma_nome="Turma B",
            pacote_codigo="200",
            retirado=False,
            arquivo_origem="Itens.csv",
            row_hash="hash-pendente",
            origem=OrigemDados.LEGADO,
        )
        self.client.force_login(usuario)

        response = self.client.get(
            reverse("cme_home"),
            {"status": "pendente", "movimentacao": Movimentacao.Tipo.ENTRADA},
        )

        self.assertContains(response, "Aluno Pendente")
        self.assertContains(response, "Não retirado")
        self.assertNotContains(response, "Aluno Retirado")

    @patch("gestao_cme.integrations.eduq.build_opener")
    def test_cliente_eduq_ignora_proxy_por_padrao(
        self, build_opener_mock: MagicMock
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read = lambda: b'{"sucesso": true}'
        build_opener_mock.return_value.open.return_value = response
        config = ConfigEduq(
            dominio="dominio",
            usuario="usuario",
            senha="senha",
            auth_url="https://eduq.test/auth",
            data_url="https://eduq.test/data",
            consulta_turmas_id=4,
            consulta_detalhes_turma_id=5,
            verify_tls=False,
            timeout=30,
            use_proxy=False,
        )

        EduqClient(config)._post_json("https://eduq.test/auth", {})

        handlers = build_opener_mock.call_args.args
        self.assertEqual(handlers[0].proxies, {})

    def test_listagem_de_alunos_nao_exibe_academicos_de_exemplo(self) -> None:
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

    def test_botao_sincronizacao_aparece_para_usuario_comum(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("alunos_por_turma"))

        self.assertContains(response, "Sincronizar turmas")
        self.assertContains(response, reverse("sincronizar_turmas_eduq"))

    def test_alunos_por_turma_exibe_ultima_sincronizacao(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        sincronizado_em = timezone.now().replace(second=0, microsecond=0)
        turma = Turma.objects.create(
            codigo="T-EDUQ",
            nome="Turma Eduq",
            origem=OrigemDados.EDUQ,
            ultima_sincronizacao=sincronizado_em,
        )
        aluno = Aluno.objects.create(
            matricula="A-EDUQ",
            nome="Aluno Eduq",
            turma=turma,
            origem=OrigemDados.EDUQ,
            ultima_sincronizacao=sincronizado_em,
        )
        Emprestimo.objects.create(aluno=aluno, coordenador_usuario=usuario)
        self.client.force_login(usuario)

        response = self.client.get(reverse("alunos_por_turma"))

        data_formatada = timezone.localtime(sincronizado_em).strftime("%d/%m/%Y %H:%M")
        self.assertContains(response, "Última sincronização")
        self.assertContains(response, data_formatada)

    def test_materiais_exibe_dados_reais_migrados(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        Material.objects.create(
            nome="KIT CIRURGICO",
            codigo="MATLEG-1",
            identificacao="KIT 1",
            rotulo_kit="KIT 1 - KIT CIRURGICO",
            disponivel=True,
            origem=OrigemDados.LEGADO,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("materiais"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_cme/materiais.html")
        self.assertContains(response, "KIT CIRURGICO")
        self.assertContains(response, "KIT 1")
        self.assertContains(response, "Disponível")

    def test_armarios_exibe_abrigos_reais_e_filtra_ocupacao(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        Abrigo.objects.create(
            identificador="150",
            ocupado=True,
            origem=OrigemDados.LEGADO,
        )
        Abrigo.objects.create(
            identificador="151",
            ocupado=False,
            origem=OrigemDados.LEGADO,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("abrigos"), {"ocupacao": "ocupado"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_cme/armarios.html")
        self.assertContains(response, "150")
        self.assertContains(response, "Ocupado")
        self.assertNotContains(response, "151")

    def test_kits_exibe_dados_reais_e_materiais_vinculados(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        kit = Kit.objects.create(
            nome="KIT CIRURGICO",
            codigo="KITLEG-1",
            quantidade=2,
            origem=OrigemDados.LEGADO,
        )
        material = Material.objects.create(
            nome="KIT CIRURGICO",
            codigo="MATLEG-1",
            identificacao="KIT 1",
            rotulo_kit="KIT 1 - KIT CIRURGICO",
            disponivel=True,
            origem=OrigemDados.LEGADO,
        )
        KitMaterial.objects.create(kit=kit, material=material, quantidade=1)
        self.client.force_login(usuario)

        response = self.client.get(reverse("kits"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_cme/kits.html")
        self.assertContains(response, "KIT CIRURGICO")
        self.assertContains(response, "KITLEG-1")
        self.assertContains(response, "KIT 1")

    @patch("gestao_cme.views.sincronizar_eduq")
    def test_botao_sincroniza_turmas_sem_sincronizar_alunos(
        self, sync_mock: MagicMock
    ) -> None:
        sync_mock.return_value = SimpleNamespace(
            turmas=SimpleNamespace(criados=2, atualizados=3, erros=[]),
        )
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"), follow=True)

        sync_mock.assert_called_once_with(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
        self.assertRedirects(response, reverse("alunos_por_turma"))
        self.assertContains(response, "Turmas sincronizadas: 2 criadas, 3 atualizadas")

    @patch("gestao_cme.views.sincronizar_eduq")
    def test_sincronizacao_de_turmas_exibe_erro_da_api(
        self, sync_mock: MagicMock
    ) -> None:
        sync_mock.side_effect = EduqAPIError("API indisponivel")
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
            is_staff=True,
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"), follow=True)

        self.assertContains(response, "Não foi possível sincronizar turmas")
        self.assertContains(response, "API indisponivel")

    @patch("gestao_cme.views.sincronizar_eduq")
    def test_usuario_comum_pode_sincronizar_turmas(self, sync_mock: MagicMock) -> None:
        sync_mock.return_value = SimpleNamespace(
            turmas=SimpleNamespace(criados=1, atualizados=0, erros=[]),
        )
        usuario = get_user_model().objects.create_user(
            username="coordenador",
            password="senha-segura",
        )
        self.client.force_login(usuario)

        response = self.client.post(reverse("sincronizar_turmas_eduq"), follow=True)

        sync_mock.assert_called_once_with(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
        self.assertRedirects(response, reverse("alunos_por_turma"))
        self.assertContains(response, "Turmas sincronizadas")


class EduqSyncTests(TestCase):
    def test_sincroniza_turmas_e_alunos_do_payload_eduq(self) -> None:
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
                "Descricao": "RIO VERDE",
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
        self.assertEqual(turma.observacoes, "Matriculas ativas: 11")
        self.assertEqual(turma.origem, OrigemDados.EDUQ)
        self.assertIsNotNone(turma.ultima_sincronizacao)
        aluno = Aluno.objects.select_related("turma").get(matricula="A-20260001")
        self.assertEqual(aluno.nome, "Ana Clara Ribeiro")
        self.assertEqual(aluno.telefone, "(62) 99901-0001")
        self.assertEqual(aluno.cidade, "RIO VERDE")
        self.assertEqual(aluno.uf, "GO")
        self.assertEqual(aluno.turma.codigo, "50057")
        self.assertEqual(aluno.origem, OrigemDados.EDUQ)
        self.assertIsNotNone(aluno.ultima_sincronizacao)

    def test_sincronizacao_e_idempotente_por_codigo_e_matricula(self) -> None:
        sincronizar_turmas_eduq([{"codigo": "IMP-2026-1", "nome": "Implantodontia"}])
        sincronizar_alunos_eduq(
            [
                {
                    "matricula": "20260002",
                    "nome": "Bruno Almeida",
                    "codigoTurma": "IMP-2026-1",
                }
            ]
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

    def test_aluno_com_turma_inexistente_retorna_erro_sem_criar_registro(
        self,
    ) -> None:
        resumo = sincronizar_alunos_eduq(
            [
                {
                    "matricula": "20260003",
                    "nome": "Carolina Sousa",
                    "codigoTurma": "TURMA-X",
                }
            ]
        )

        self.assertEqual(resumo.criados, 0)
        self.assertEqual(len(resumo.erros), 1)
        self.assertFalse(Aluno.objects.exists())

    def test_sincronizacao_permite_cpfs_duplicados_quando_ids_eduq_sao_diferentes(
        self,
    ) -> None:
        Turma.objects.create(
            codigo="TURMA-CPF", nome="Turma CPF", origem=OrigemDados.EDUQ
        )

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

    def test_atualiza_localizacao_de_alunos_existentes_pelo_eduq(self) -> None:
        turma = Turma.objects.create(
            codigo="50057", nome="Turma Eduq", origem=OrigemDados.EDUQ
        )
        aluno = Aluno.objects.create(
            nome="Monara Cruvinel Moreira",
            matricula="15.ESP.E.O.20230505612",
            cpf="101.222.333-44",
            turma=turma,
            origem=OrigemDados.EDUQ,
        )

        class FakeEduqClient:
            codigo_consultado = None

            def listar_alunos(self, codigo_turma_eduq: str) -> list[AlunoEduq]:
                self.codigo_consultado = codigo_turma_eduq
                return [
                    AlunoEduq(
                        matricula="15.ESP.E.O.20230505612",
                        nome="MONARA CRUVINEL MOREIRA",
                        cpf="101.222.333-44",
                        cidade="RIO VERDE",
                        uf="GO",
                        turma_codigo="50057",
                    )
                ]

        client = FakeEduqClient()
        total = sincronizar_localizacao_alunos_turma(turma, client=client)

        self.assertEqual(total, 1)
        self.assertEqual(client.codigo_consultado, "50057")
        aluno.refresh_from_db()
        self.assertEqual(aluno.cidade, "RIO VERDE")
        self.assertEqual(aluno.uf, "GO")

    def test_sincronizacao_consulta_alunos_por_turma_eduq(self) -> None:
        class FakeEduqClient:
            codigos_consultados = []

            def listar_turmas(self) -> list[TurmaEduq]:
                return [
                    TurmaEduq(codigo="TURMA-1", nome="Turma 1"),
                    TurmaEduq(codigo="TURMA-2", nome="Turma 2"),
                ]

            def listar_alunos(self, codigo_turma_eduq: str) -> list[AlunoEduq]:
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

    def test_sincronizacao_de_alunos_continua_quando_uma_turma_falha(self) -> None:
        class FakeEduqClient:
            def listar_turmas(self) -> list[TurmaEduq]:
                return [
                    TurmaEduq(codigo="TURMA-OK", nome="Turma OK"),
                    TurmaEduq(codigo="TURMA-ERRO", nome="Turma Erro"),
                ]

            def listar_alunos(self, codigo_turma_eduq: str) -> list[AlunoEduq]:
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

    def test_sincronizacao_de_alunos_em_massa_ignora_turmas_de_exemplo(
        self,
    ) -> None:
        Turma.objects.create(
            codigo="TURMA-EDUQ", nome="Turma Eduq", origem=OrigemDados.EDUQ
        )
        Turma.objects.create(
            codigo="TURMA-EXEMPLO",
            nome="Turma Exemplo",
            origem=OrigemDados.EXEMPLO,
        )

        class FakeEduqClient:
            codigos_consultados = []

            def listar_turmas(self) -> list[TurmaEduq]:
                raise AssertionError("Nao deve consultar turmas quando somente alunos.")

            def listar_alunos(self, codigo_turma_eduq: str) -> list[AlunoEduq]:
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
    def test_fixture_de_exemplo_nao_cria_dados_academicos_fake(self) -> None:
        fixture_path = (
            settings.BASE_DIR / "gestao_cme" / "fixtures" / "dados_exemplo.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        modelos = {item["model"] for item in data}

        self.assertNotIn("core.turma", modelos)
        self.assertNotIn("core.aluno", modelos)
        self.assertNotIn("core.emprestimo", modelos)
        self.assertNotIn("core.itememprestimo", modelos)
        self.assertIn("core.material", modelos)
        self.assertIn("core.kit", modelos)
        self.assertIn("core.armario", modelos)

    def test_fixture_de_exemplo_carrega_apenas_dados_operacionais(self) -> None:
        call_command("loaddata", "dados_exemplo", verbosity=0)

        self.assertFalse(Turma.objects.exists())
        self.assertFalse(Aluno.objects.exists())
        self.assertTrue(Material.objects.exists())
        self.assertTrue(Armario.objects.exists())


class MigracaoLegadoTests(TestCase):
    def test_migra_dados_operacionais_legados_para_o_banco(self) -> None:
        with patch(
            "gestao_cme.services.migracao_legado._ler_csv",
            side_effect=self._ler_csv_mock,
        ):
            resultado = migrar_dados_legado("csvs")

        self.assertEqual(resultado.abrigos.criados, 2)
        self.assertEqual(resultado.kits.criados, 1)
        self.assertEqual(resultado.materiais.criados, 2)
        self.assertEqual(resultado.movimentacoes.criados, 2)
        self.assertEqual(Abrigo.objects.filter(ocupado=True).count(), 1)
        self.assertEqual(Kit.objects.get().quantidade, 2)
        self.assertEqual(Material.objects.filter(disponivel=True).count(), 1)
        self.assertEqual(Material.objects.filter(disponivel=False).count(), 1)
        self.assertTrue(
            Movimentacao.objects.filter(tipo=Movimentacao.Tipo.SAIDA).exists()
        )
        self.assertTrue(
            Movimentacao.objects.filter(tipo=Movimentacao.Tipo.ENTRADA).exists()
        )

    def test_migracao_legado_e_idempotente(self) -> None:
        with patch(
            "gestao_cme.services.migracao_legado._ler_csv",
            side_effect=self._ler_csv_mock,
        ):
            migrar_dados_legado("csvs")
            resultado = migrar_dados_legado("csvs")

        self.assertEqual(resultado.abrigos.atualizados, 2)
        self.assertEqual(resultado.kits.atualizados, 1)
        self.assertEqual(resultado.materiais.atualizados, 2)
        self.assertEqual(resultado.movimentacoes.atualizados, 2)
        self.assertEqual(Abrigo.objects.count(), 2)
        self.assertEqual(Kit.objects.count(), 1)
        self.assertEqual(Material.objects.count(), 2)
        self.assertEqual(Movimentacao.objects.count(), 2)

    def _ler_csv_mock(self, path: Path) -> list[dict[str, str]]:
        dados = {
            "Abrigos.csv": [
                {"Identificador": "1", "Ocupado": "true"},
                {"Identificador": "2", "Ocupado": "false"},
            ],
            "Kits.csv": [
                {"Kit": "KIT CIRURGICO", "Quantidade": "2", "Apagar": "system"},
            ],
            "Materiais para empréstimo.csv": [
                {
                    "Material": "KIT CIRURGICO",
                    "Identificação": "KIT 1",
                    "Kit": "KIT 1 - KIT CIRURGICO",
                    "Ativo": "true",
                    "Disponivel": "true",
                    "Apagar": "model",
                },
                {
                    "Material": "KIT CIRURGICO",
                    "Identificação": "KIT 2",
                    "Kit": "KIT 2 - KIT CIRURGICO",
                    "Ativo": "true",
                    "Disponivel": "false",
                    "Apagar": "model",
                },
            ],
            "Relatório de movimentação.csv": [
                {
                    "Data": "29/05/2026, 07:58",
                    "Nome": "817 - Maria Eduarda",
                    "Turma": "Turma Real",
                    "Movimentação": "Saída",
                    "Pacote": "4801",
                    "Retirado": "true",
                    "Apagar": "model",
                },
            ],
            "Itens não retirados.csv": [
                {
                    "Data": "25/03/2024, 15:26",
                    "Nome": "- Maria Eduarda",
                    "Turma": "Turma Real",
                    "Movimentação": "Entrada",
                    "Pacote": "4801",
                    "Entregar": "model",
                },
            ],
        }
        return dados[path.name]


class RequerGrupoTests(TestCase):
    """Testa o decorator isoladamente — ele ainda não está aplicado a
    nenhuma view real, então a checagem é feita numa view trivial criada
    só para o teste."""

    def setUp(self) -> None:
        self.factory = RequestFactory()

        @requer_grupo(GRUPO_GESTAO)
        def view(request):
            return HttpResponse("ok")

        self.view = view

    def test_usuario_anonimo_redireciona_para_login(self) -> None:
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/qualquer-rota/")
        request.user = AnonymousUser()

        response = self.view(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_usuario_sem_grupo_recebe_permission_denied(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="sem-grupo", password="senha-segura"
        )
        request = self.factory.get("/qualquer-rota/")
        request.user = usuario

        with self.assertRaises(PermissionDenied):
            self.view(request)

    def test_usuario_no_grupo_correto_acessa(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="da-gestao", password="senha-segura"
        )
        usuario.groups.add(Group.objects.create(name=GRUPO_GESTAO))
        request = self.factory.get("/qualquer-rota/")
        request.user = usuario

        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_superuser_acessa_sem_pertencer_a_nenhum_grupo(self) -> None:
        usuario = get_user_model().objects.create_superuser(
            username="admin", password="senha-segura", email="admin@example.com"
        )
        request = self.factory.get("/qualquer-rota/")
        request.user = usuario

        response = self.view(request)

        self.assertEqual(response.status_code, 200)


class CriarGruposPadraoTests(TestCase):
    def test_cria_os_tres_grupos_padrao(self) -> None:
        call_command("criar_grupos_padrao")

        self.assertEqual(
            Group.objects.filter(name__in=GRUPOS_PADRAO).count(), len(GRUPOS_PADRAO)
        )

    def test_comando_e_idempotente(self) -> None:
        call_command("criar_grupos_padrao")
        call_command("criar_grupos_padrao")

        self.assertEqual(
            Group.objects.filter(name__in=GRUPOS_PADRAO).count(), len(GRUPOS_PADRAO)
        )


class MenuDoUsuarioTests(TestCase):
    def test_dropdown_exibe_trocar_senha_e_sair(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="comum", password="senha-segura"
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "user-menu-dropdown")
        self.assertContains(response, "Trocar senha")
        self.assertContains(response, "Sair")

    def test_dropdown_esconde_administracao_para_usuario_comum(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="comum2", password="senha-segura"
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("home"))

        self.assertNotContains(response, "Administração")

    def test_dropdown_exibe_administracao_para_staff(self) -> None:
        usuario = get_user_model().objects.create_user(
            username="staff", password="senha-segura", is_staff=True
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Administração")


class PaginasDeErroTests(TestCase):
    """Os templates 404/403/500 estendem auth/base_auth.html porque as views
    padrão do Django (django.views.defaults) renderizam sem context
    processors — 500 nem recebe request. Por isso os testes chamam as views
    diretamente com RequestFactory em vez de depender do Client."""

    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _request_autenticado(self, path: str):
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get(path)
        # page_not_found/permission_denied passam `request` ao template (ao
        # contrário de server_error) — o context processor usuario_logado
        # precisa de request.user, normalmente populado pelo
        # AuthenticationMiddleware. RequestFactory não roda middleware, então
        # simulamos aqui um visitante anônimo.
        request.user = AnonymousUser()
        return request

    def test_pagina_404_renderiza(self) -> None:
        from django.http import Http404
        from django.views.defaults import page_not_found

        request = self._request_autenticado("/rota-que-nao-existe/")
        response = page_not_found(request, Http404("não encontrado"))

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"P\xc3\xa1gina n\xc3\xa3o encontrada", response.content)

    def test_pagina_403_renderiza(self) -> None:
        from django.views.defaults import permission_denied

        request = self._request_autenticado("/qualquer-rota/")
        response = permission_denied(request, PermissionDenied())

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Sem permiss\xc3\xa3o", response.content)

    def test_pagina_500_renderiza_sem_contexto(self) -> None:
        from django.views.defaults import server_error

        request = self.factory.get("/qualquer-rota/")
        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Erro interno", response.content)


class SincronizacaoAgendadaEduqTests(TestCase):
    """A rotina em segundo plano que mantem a base de alunos completa."""

    @patch("gestao_cme.services.eduq_sync.sincronizar_eduq")
    def test_task_sincroniza_turmas_e_alunos_e_resume(self, mock_sync) -> None:
        from gestao_cme.tasks import sincronizar_eduq_task

        mock_sync.return_value = SimpleNamespace(
            turmas=SimpleNamespace(criados=2, atualizados=41, erros=[]),
            alunos=SimpleNamespace(criados=5, atualizados=370, erros=["x"]),
        )

        resumo = sincronizar_eduq_task()

        mock_sync.assert_called_once_with(
            sincronizar_turmas=True, sincronizar_alunos=True
        )
        self.assertEqual(resumo["turmas_criadas"], 2)
        self.assertEqual(resumo["alunos_criados"], 5)
        self.assertEqual(resumo["erros"], 1)

    def test_task_esta_agendada_no_beat(self) -> None:
        """Sem entrada no Beat a rotina nunca roda — e a base fica parada."""

        agendamentos = settings.CELERY_BEAT_SCHEDULE.values()
        tarefas = {item["task"] for item in agendamentos}

        self.assertIn("gestao_cme.tasks.sincronizar_eduq_task", tarefas)
        self.assertIn("gestao_lab.tasks.sincronizar_dental_task", tarefas)


@override_settings(ALLOWED_HOSTS=["testserver"])
class MateriaisFase32Tests(TestCase):
    """Autocomplete de aluno, atualizacao via Eduq e exclusao de material (Fase 3.2)."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-3-2", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.turma = Turma.objects.create(
            nome="Turma X", codigo="TX", origem=OrigemDados.EDUQ
        )
        self.aluno = Aluno.objects.create(
            nome="Carlos Andrade",
            matricula="MAT-1",
            turma=self.turma,
            origem=OrigemDados.EDUQ,
        )
        Aluno.objects.create(
            nome="Outro Nome",
            matricula="MAT-2",
            turma=self.turma,
            origem=OrigemDados.EDUQ,
        )

    def test_buscar_alunos_filtra_por_nome(self) -> None:
        response = self.client.get(reverse("buscar_alunos"), {"q": "Carlos"})

        self.assertContains(response, "Carlos Andrade")
        self.assertNotContains(response, "Outro Nome")

    def test_buscar_alunos_ignora_acento(self) -> None:
        """Os cadastros vem do Eduq com grafia mista e o operador digita sem
        acento — as duas formas precisam encontrar o mesmo conjunto."""

        Aluno.objects.create(
            nome="Ana Júlia Gonçalves",
            matricula="MAT-9",
            turma=self.turma,
            origem=OrigemDados.EDUQ,
        )

        for termo in ("Goncalves", "Gonçalves", "JULIA", "júlia"):
            with self.subTest(termo=termo):
                response = self.client.get(reverse("buscar_alunos"), {"q": termo})
                self.assertContains(response, "Ana Júlia Gonçalves")

    def test_nome_normalizado_e_derivado_do_nome(self) -> None:
        aluno = Aluno.objects.create(
            nome="José da Silva Araújo",
            matricula="MAT-10",
            turma=self.turma,
            origem=OrigemDados.EDUQ,
        )
        self.assertEqual(aluno.nome_normalizado, "JOSE DA SILVA ARAUJO")

        # o derivado acompanha a renomeacao, inclusive com update_fields
        aluno.nome = "João Pereira"
        aluno.save(update_fields=["nome"])
        aluno.refresh_from_db()
        self.assertEqual(aluno.nome_normalizado, "JOAO PEREIRA")

    def test_campo_de_busca_de_aluno_envia_o_termo(self) -> None:
        """Regressão: sem `name` no input, o HTMX não envia `q` e a listagem
        devolve sempre todos os alunos — a busca parece 'não atualizar'."""

        import re

        for rota in ("registrar_entrada", "registrar_saida"):
            with self.subTest(rota=rota):
                conteudo = self.client.get(reverse(rota)).content.decode()
                campos = re.findall(r"<input[^>]*type=\"search\"[^>]*>", conteudo)

                self.assertTrue(campos, "esperado um campo de busca de aluno")
                for campo in campos:
                    self.assertIn('name="q"', campo)
                    self.assertIn("hx-get=", campo)

    def test_buscar_alunos_pendencias_so_alunos_com_pacotes(self) -> None:
        vazio = self.client.get(reverse("buscar_alunos"), {"pendencias": "1"})
        self.assertNotContains(vazio, "Carlos Andrade")

        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno=self.aluno,
            aluno_nome=self.aluno.nome,
            pacote_codigo="1",
            retirado=False,
            arquivo_origem="painel",
            row_hash="h1",
            origem=OrigemDados.MANUAL,
        )
        com = self.client.get(reverse("buscar_alunos"), {"pendencias": "1"})
        self.assertContains(com, "Carlos Andrade")

    def test_excluir_material_sem_vinculos(self) -> None:
        material = Material.objects.create(
            nome="Livre", codigo="C-LIVRE", origem=OrigemDados.MANUAL
        )
        response = self.client.post(reverse("excluir_material", args=[material.pk]))

        self.assertRedirects(response, reverse("materiais"))
        self.assertFalse(Material.objects.filter(pk=material.pk).exists())

    def test_excluir_material_com_emprestimo_e_bloqueado(self) -> None:
        material = Material.objects.create(
            nome="Vinculado", codigo="C-VINC", origem=OrigemDados.MANUAL
        )
        emp = Emprestimo.objects.create(
            aluno=self.aluno, status=Emprestimo.Status.EMPRESTADO
        )
        ItemEmprestimo.objects.create(emprestimo=emp, material=material, quantidade=3)

        response = self.client.post(reverse("excluir_material", args=[material.pk]))

        self.assertRedirects(response, reverse("editar_material", args=[material.pk]))
        self.assertTrue(Material.objects.filter(pk=material.pk).exists())

    def test_editar_material_expoe_unidades_em_emprestimo(self) -> None:
        material = Material.objects.create(
            nome="Vinculado2", codigo="C-VINC2", origem=OrigemDados.MANUAL
        )
        emp = Emprestimo.objects.create(
            aluno=self.aluno, status=Emprestimo.Status.ATRASADO
        )
        ItemEmprestimo.objects.create(emprestimo=emp, material=material, quantidade=5)

        response = self.client.get(reverse("editar_material", args=[material.pk]))

        self.assertEqual(response.context["em_emprestimo"], 5)

    @patch("gestao_cme.views.sincronizar_eduq")
    def test_atualizar_alunos_eduq_dispara_sync_e_redireciona(self, mock_sync) -> None:
        mock_sync.return_value = SimpleNamespace(
            alunos=SimpleNamespace(criados=2, atualizados=1),
        )
        response = self.client.post(reverse("atualizar_alunos_eduq"))

        self.assertTrue(mock_sync.called)
        self.assertEqual(response.status_code, 302)


class KitCrudTests(TestCase):
    """Cadastro/edição/exclusão de kit pela interface, com quantidade por
    material na composição e Kit.quantidade como estoque cadastrado
    manualmente, independente da disponibilidade dos materiais (decisões de
    negócio de 2026-07)."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-kits", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.material_disponivel = Material.objects.create(
            nome="Espelho clínico",
            codigo="KC-001",
            disponivel=True,
            origem=OrigemDados.MANUAL,
        )
        self.material_indisponivel = Material.objects.create(
            nome="Sonda exploradora",
            codigo="KC-002",
            disponivel=False,
            origem=OrigemDados.MANUAL,
        )

    def test_cadastrar_kit_define_quantidade_por_material(self) -> None:
        response = self.client.post(
            reverse("cadastrar_kit"),
            {
                "nome": "Kit Exame",
                "codigo": "KIT-EXAME",
                "descricao": "",
                "quantidade": "1",
                "materiais": [self.material_disponivel.pk],
                f"quantidade_{self.material_disponivel.pk}": "4",
            },
        )

        self.assertRedirects(response, reverse("kits"))
        kit = Kit.objects.get(codigo="KIT-EXAME")
        item = KitMaterial.objects.get(kit=kit, material=self.material_disponivel)
        self.assertEqual(item.quantidade, 4)

    def test_cadastrar_kit_define_quantidade_em_estoque_manualmente(self) -> None:
        response = self.client.post(
            reverse("cadastrar_kit"),
            {
                "nome": "Kit Misto",
                "codigo": "KIT-MISTO",
                "descricao": "",
                "quantidade": "7",
                "materiais": [
                    self.material_disponivel.pk,
                    self.material_indisponivel.pk,
                ],
                f"quantidade_{self.material_disponivel.pk}": "1",
                f"quantidade_{self.material_indisponivel.pk}": "1",
            },
        )

        self.assertRedirects(response, reverse("kits"))
        kit = Kit.objects.get(codigo="KIT-MISTO")
        # Quantidade é o estoque cadastrado, informado manualmente — não
        # depende de quantos dos 2 materiais vinculados estão disponíveis.
        self.assertEqual(kit.quantidade, 7)

    def test_editar_kit_atualiza_composicao_sem_alterar_quantidade_automaticamente(
        self,
    ) -> None:
        kit = Kit.objects.create(
            nome="Kit Ajustável",
            codigo="KIT-AJUST",
            quantidade=99,
            origem=OrigemDados.MANUAL,
        )
        KitMaterial.objects.create(
            kit=kit, material=self.material_disponivel, quantidade=1
        )

        response = self.client.post(
            reverse("editar_kit", args=[kit.pk]),
            {
                "nome": "Kit Ajustável",
                "codigo": "KIT-AJUST",
                "descricao": "",
                "quantidade": "99",
                "ativo": "on",
                "materiais": [self.material_indisponivel.pk],
                f"quantidade_{self.material_indisponivel.pk}": "2",
            },
        )

        self.assertRedirects(response, reverse("kits"))
        kit.refresh_from_db()
        # material antigo saiu, novo entrou com quantidade 2 — e o estoque
        # cadastrado (99) não muda, mesmo o novo material não estando
        # disponível: são conceitos independentes.
        self.assertFalse(
            KitMaterial.objects.filter(
                kit=kit, material=self.material_disponivel
            ).exists()
        )
        item_novo = KitMaterial.objects.get(
            kit=kit, material=self.material_indisponivel
        )
        self.assertEqual(item_novo.quantidade, 2)
        self.assertEqual(kit.quantidade, 99)

    def test_excluir_kit_sem_vinculos(self) -> None:
        kit = Kit.objects.create(
            nome="Kit Livre", codigo="KIT-LIVRE", origem=OrigemDados.MANUAL
        )

        response = self.client.post(reverse("excluir_kit", args=[kit.pk]))

        self.assertRedirects(response, reverse("kits"))
        self.assertFalse(Kit.objects.filter(pk=kit.pk).exists())

    def test_excluir_kit_com_emprestimo_e_bloqueado(self) -> None:
        kit = Kit.objects.create(
            nome="Kit Vinculado", codigo="KIT-VINC", origem=OrigemDados.MANUAL
        )
        turma = Turma.objects.create(
            nome="Turma K", codigo="TK", origem=OrigemDados.MANUAL
        )
        aluno = Aluno.objects.create(
            nome="Aluno Kit", matricula="MATKIT", turma=turma, origem=OrigemDados.MANUAL
        )
        Emprestimo.objects.create(
            aluno=aluno, kit=kit, status=Emprestimo.Status.EMPRESTADO
        )

        response = self.client.post(reverse("excluir_kit", args=[kit.pk]))

        self.assertRedirects(response, reverse("editar_kit", args=[kit.pk]))
        self.assertTrue(Kit.objects.filter(pk=kit.pk).exists())

    def test_editar_kit_expoe_emprestimos_ativos(self) -> None:
        kit = Kit.objects.create(
            nome="Kit Emprestado", codigo="KIT-EMP", origem=OrigemDados.MANUAL
        )
        turma = Turma.objects.create(
            nome="Turma E", codigo="TE", origem=OrigemDados.MANUAL
        )
        aluno = Aluno.objects.create(
            nome="Aluno Emp", matricula="MATEMP", turma=turma, origem=OrigemDados.MANUAL
        )
        Emprestimo.objects.create(
            aluno=aluno, kit=kit, status=Emprestimo.Status.ATRASADO
        )

        response = self.client.get(reverse("editar_kit", args=[kit.pk]))

        self.assertEqual(response.context["em_emprestimo"], 1)

    def test_kits_listagem_tem_link_de_edicao(self) -> None:
        kit = Kit.objects.create(
            nome="Kit Listado", codigo="KIT-LIST", origem=OrigemDados.MANUAL
        )

        response = self.client.get(reverse("kits"))

        self.assertContains(response, reverse("editar_kit", args=[kit.pk]))


class AuditoriaMovimentacaoTests(TestCase):
    """Trilha mínima (usuário, ação, quando) para edição/exclusão de
    movimentação — decisão de negócio de 2026-07."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-auditoria", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.mov = Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno_nome="Aluno Auditado",
            pacote_codigo="9001",
            retirado=False,
            arquivo_origem="painel",
            row_hash="hash-auditoria-1",
            origem=OrigemDados.MANUAL,
        )

    def test_editar_movimentacao_grava_auditoria(self) -> None:
        response = self.client.post(
            reverse("editar_movimentacao", args=[self.mov.pk]),
            {
                "pacote_codigo": "9001-B",
                "data_hora": "2026-07-20T10:00",
                "observacoes": "",
            },
        )

        self.assertRedirects(response, reverse("cme_home"))
        registro = RegistroAuditoriaMovimentacao.objects.get(movimentacao=self.mov)
        self.assertEqual(registro.acao, RegistroAuditoriaMovimentacao.Acao.EDICAO)
        self.assertEqual(registro.usuario, self.usuario)
        self.assertEqual(registro.pacote_codigo, "9001-B")

    def test_excluir_movimentacao_grava_auditoria_e_sobrevive_ao_delete(self) -> None:
        response = self.client.post(reverse("excluir_movimentacao", args=[self.mov.pk]))

        self.assertRedirects(response, reverse("cme_home"))
        self.assertFalse(Movimentacao.objects.filter(pk=self.mov.pk).exists())

        registro = RegistroAuditoriaMovimentacao.objects.get(pacote_codigo="9001")
        self.assertEqual(registro.acao, RegistroAuditoriaMovimentacao.Acao.EXCLUSAO)
        self.assertEqual(registro.usuario, self.usuario)
        self.assertEqual(registro.aluno_nome, "Aluno Auditado")
        # A movimentacao original foi apagada; a FK acompanha via SET_NULL.
        self.assertIsNone(registro.movimentacao)

    def test_editar_movimentacao_exibe_historico_de_alteracoes(self) -> None:
        RegistroAuditoriaMovimentacao.objects.create(
            movimentacao=self.mov,
            pacote_codigo=self.mov.pacote_codigo,
            aluno_nome=self.mov.aluno_nome,
            acao=RegistroAuditoriaMovimentacao.Acao.EDICAO,
            usuario=self.usuario,
        )

        response = self.client.get(reverse("editar_movimentacao", args=[self.mov.pk]))

        self.assertContains(response, "Histórico de alterações")
        self.assertContains(response, "cme-auditoria")


class SincronizarTurmaBuscaTests(TestCase):
    """Busca de aluno sem resultado oferece sincronizar a turma sob demanda
    (decisão de negócio: o Eduq não tem busca de aluno por nome)."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-sync-busca", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.turma = Turma.objects.create(
            nome="Turma Sync", codigo="TSYNC", origem=OrigemDados.EDUQ
        )

    def test_busca_sem_resultado_oferece_turmas_para_sincronizar(self) -> None:
        response = self.client.get(
            reverse("buscar_alunos"), {"q": "Alguém Que Não Existe"}
        )

        self.assertContains(response, "Sincronizar turma")
        self.assertContains(response, "Turma Sync")

    def test_busca_com_resultado_nao_oferece_sincronizar(self) -> None:
        Aluno.objects.create(
            nome="Encontrável",
            matricula="MAT-ENC",
            turma=self.turma,
            origem=OrigemDados.EDUQ,
        )

        response = self.client.get(reverse("buscar_alunos"), {"q": "Encontrável"})

        self.assertNotContains(response, "Sincronizar turma")

    def test_busca_vazia_nao_oferece_sincronizar(self) -> None:
        response = self.client.get(reverse("buscar_alunos"))

        self.assertNotContains(response, "Sincronizar turma")

    @patch("gestao_cme.views.sincronizar_eduq")
    def test_sincronizar_turma_busca_chama_sync_e_redireciona_para_next(
        self, mock_sync
    ) -> None:
        mock_sync.return_value = SimpleNamespace(
            alunos=SimpleNamespace(criados=1, atualizados=0, erros=[]),
        )

        response = self.client.post(
            reverse("sincronizar_turma_busca"),
            {"turma_id": self.turma.pk, "next": "/gestao-cme/nova-entrada/"},
        )

        mock_sync.assert_called_once_with(
            sincronizar_turmas=False,
            sincronizar_alunos=True,
            turma_codigos=[self.turma.codigo],
        )
        self.assertRedirects(
            response, "/gestao-cme/nova-entrada/", fetch_redirect_response=False
        )

    def test_sincronizar_turma_busca_sem_selecao_mostra_erro(self) -> None:
        response = self.client.post(
            reverse("sincronizar_turma_busca"), {"turma_id": "", "next": ""}
        )

        self.assertRedirects(response, reverse("alunos_por_turma"))


class EmprestimoAtrasoAutomaticoTests(TestCase):
    """Empréstimo muda para ATRASADO automaticamente ao vencer o prazo
    (decisão de negócio de 2026-07)."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-atraso", password="senha-segura", is_superuser=True
        )
        self.client.force_login(self.usuario)
        self.turma = Turma.objects.create(
            nome="Turma Atraso", codigo="TATR", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            nome="Aluno Atraso",
            matricula="MATATR",
            turma=self.turma,
            origem=OrigemDados.MANUAL,
        )

    def test_listagem_marca_emprestimo_vencido_como_atrasado(self) -> None:
        ontem = timezone.localdate() - timedelta(days=1)
        emp = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_prevista_devolucao=ontem,
        )

        response = self.client.get(reverse("emprestimos"))

        self.assertEqual(response.status_code, 200)
        emp.refresh_from_db()
        self.assertEqual(emp.status, Emprestimo.Status.ATRASADO)
        self.assertContains(response, "Atrasado")

    def test_nao_marca_atrasado_sem_prazo_definido(self) -> None:
        emp = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_prevista_devolucao=None,
        )

        self.client.get(reverse("emprestimos"))

        emp.refresh_from_db()
        self.assertEqual(emp.status, Emprestimo.Status.EMPRESTADO)

    def test_nao_reverte_emprestimo_ja_devolvido(self) -> None:
        ontem = timezone.localdate() - timedelta(days=1)
        emp = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.DEVOLVIDO,
            data_prevista_devolucao=ontem,
            data_devolucao=timezone.now(),
        )

        self.client.get(reverse("emprestimos"))

        emp.refresh_from_db()
        self.assertEqual(emp.status, Emprestimo.Status.DEVOLVIDO)

    def test_nao_marca_atrasado_antes_do_prazo(self) -> None:
        amanha = timezone.localdate() + timedelta(days=1)
        emp = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_prevista_devolucao=amanha,
        )

        self.client.get(reverse("emprestimos"))

        emp.refresh_from_db()
        self.assertEqual(emp.status, Emprestimo.Status.EMPRESTADO)

    def test_servico_retorna_quantidade_marcada(self) -> None:
        from gestao_cme.services.emprestimos import marcar_emprestimos_atrasados

        ontem = timezone.localdate() - timedelta(days=1)
        Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_prevista_devolucao=ontem,
        )

        total = marcar_emprestimos_atrasados()

        self.assertEqual(total, 1)


class EmprestimosFiltroPeriodoTests(TestCase):
    """Filtro de período em Empréstimos (item 11 da avaliação visual) — antes
    só existia em Movimentações/Visão Geral; recorta por ``data_emprestimo``,
    mesmo formato ISO do <input type="date"> usado nas outras telas."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-emp-periodo", password="senha-segura", is_superuser=True
        )
        self.client.force_login(self.usuario)
        self.turma = Turma.objects.create(
            nome="Turma Periodo Emp", codigo="TPEMP", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            nome="Aluno Periodo Emp",
            matricula="MATPEMP",
            turma=self.turma,
            origem=OrigemDados.MANUAL,
        )
        self.dentro = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_emprestimo=datetime(2026, 3, 10, 10, 0, tzinfo=dt_timezone.utc),
        )
        self.fora = Emprestimo.objects.create(
            aluno=self.aluno,
            status=Emprestimo.Status.EMPRESTADO,
            data_emprestimo=datetime(2026, 8, 10, 10, 0, tzinfo=dt_timezone.utc),
        )

    def test_filtro_periodo_iso_recorta_listagem_e_metricas(self) -> None:
        response = self.client.get(
            reverse("emprestimos"),
            {"data_inicio": "2026-01-01", "data_fim": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        emprestimos = list(response.context["emprestimos"])
        self.assertIn(self.dentro, emprestimos)
        self.assertNotIn(self.fora, emprestimos)
        self.assertEqual(response.context["metricas"]["total"], 1)

    def test_formulario_usa_input_type_date(self) -> None:
        response = self.client.get(reverse("emprestimos"))

        self.assertContains(response, 'type="date"')

    def test_data_invalida_e_ignorada_sem_erro(self) -> None:
        response = self.client.get(
            reverse("emprestimos"), {"data_inicio": "31/12/2026"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["data_inicio_str"], "")


class EditarEmprestimoTests(TestCase):
    """Edição de empréstimo (item 10 da avaliação visual) — só data prevista
    de devolução e observações são editáveis, e a visibilidade segue a mesma
    regra de ``emprestimos_visiveis`` usada na listagem e nas outras ações."""

    def setUp(self) -> None:
        self.turma = Turma.objects.create(
            nome="Turma Editar", codigo="TEDIT", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            nome="Aluno Editar",
            matricula="MATEDIT",
            turma=self.turma,
            origem=OrigemDados.MANUAL,
        )
        self.coordenador = get_user_model().objects.create_user(
            username="cme-coord-editar", password="senha-segura"
        )
        self.outro_coordenador = get_user_model().objects.create_user(
            username="cme-outro-editar", password="senha-segura"
        )
        self.superusuario = get_user_model().objects.create_user(
            username="cme-super-editar", password="senha-segura", is_superuser=True
        )
        self.emp = Emprestimo.objects.create(
            aluno=self.aluno,
            coordenador_usuario=self.coordenador,
            status=Emprestimo.Status.EMPRESTADO,
            data_prevista_devolucao=timezone.localdate() + timedelta(days=5),
            observacoes="Observação original",
        )

    def test_get_exibe_formulario_preenchido(self) -> None:
        self.client.force_login(self.coordenador)

        response = self.client.get(reverse("editar_emprestimo", args=[self.emp.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Observação original")
        self.assertContains(response, self.aluno.nome)
        # input type="date" só aceita ISO (aaaa-mm-dd) — não o "27 de Julho
        # de 2026" que o template geraria sem a formatação explícita.
        data_iso = self.emp.data_prevista_devolucao.isoformat()
        self.assertContains(response, f'value="{data_iso}"')

    def test_post_atualiza_data_e_observacoes(self) -> None:
        self.client.force_login(self.coordenador)
        nova_data = timezone.localdate() + timedelta(days=10)

        response = self.client.post(
            reverse("editar_emprestimo", args=[self.emp.pk]),
            {
                "data_prevista_devolucao": nova_data.isoformat(),
                "observacoes": "Observação atualizada",
            },
        )

        self.assertRedirects(response, reverse("emprestimos"))
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.data_prevista_devolucao, nova_data)
        self.assertEqual(self.emp.observacoes, "Observação atualizada")

    def test_coordenador_nao_acessa_emprestimo_de_outro(self) -> None:
        self.client.force_login(self.outro_coordenador)

        response = self.client.get(reverse("editar_emprestimo", args=[self.emp.pk]))

        self.assertEqual(response.status_code, 404)

    def test_superusuario_acessa_emprestimo_de_qualquer_coordenador(self) -> None:
        self.client.force_login(self.superusuario)

        response = self.client.get(reverse("editar_emprestimo", args=[self.emp.pk]))

        self.assertEqual(response.status_code, 200)

    def test_listagem_traz_link_de_editar(self) -> None:
        self.client.force_login(self.coordenador)

        response = self.client.get(reverse("emprestimos"))

        self.assertContains(response, reverse("editar_emprestimo", args=[self.emp.pk]))


class CmeDashboardFiltroPeriodoTests(TestCase):
    """Filtro de período da Visão Geral usa formato ISO (aaaa-mm-dd), o
    mesmo que <input type="date"> envia — decisão de negócio de 2026-07
    (calendário nativo em vez de texto livre dd/mm/aaaa)."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-dashboard", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.turma = Turma.objects.create(
            nome="Turma Dashboard", codigo="TDASH", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            nome="Aluno Dashboard",
            matricula="MATDASH",
            turma=self.turma,
            origem=OrigemDados.MANUAL,
        )
        Movimentacao.objects.create(
            data_hora=datetime(2026, 3, 10, 10, 0, tzinfo=dt_timezone.utc),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno=self.aluno,
            aluno_nome=self.aluno.nome,
            pacote_codigo="D-1",
            retirado=False,
            arquivo_origem="painel",
            row_hash="hash-dash-1",
            origem=OrigemDados.MANUAL,
        )
        Movimentacao.objects.create(
            data_hora=datetime(2026, 8, 10, 10, 0, tzinfo=dt_timezone.utc),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno=self.aluno,
            aluno_nome=self.aluno.nome,
            pacote_codigo="D-2",
            retirado=False,
            arquivo_origem="painel",
            row_hash="hash-dash-2",
            origem=OrigemDados.MANUAL,
        )

    def test_filtro_periodo_iso_recorta_metricas(self) -> None:
        response = self.client.get(
            reverse("cme_dashboard"),
            {"data_inicio": "2026-01-01", "data_fim": "2026-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["metricas_mov"]["total"], 1)
        self.assertEqual(response.context["data_inicio_str"], "2026-01-01")
        self.assertEqual(response.context["data_fim_str"], "2026-06-30")

    def test_data_invalida_e_ignorada_sem_erro(self) -> None:
        response = self.client.get(
            reverse("cme_dashboard"),
            {"data_inicio": "31/12/2026", "data_fim": ""},
        )

        self.assertEqual(response.status_code, 200)
        # formato dd/mm/aaaa nao e mais aceito (so aaaa-mm-dd) - descartado.
        self.assertEqual(response.context["data_inicio_str"], "")

    def test_kpi_link_carrega_filtro_em_formato_iso(self) -> None:
        response = self.client.get(
            reverse("cme_dashboard"),
            {"data_inicio": "2026-01-01", "data_fim": "2026-12-31"},
        )

        self.assertContains(response, "data_inicio=2026-01-01")
        self.assertContains(response, "data_fim=2026-12-31")

    def test_formulario_usa_input_type_date(self) -> None:
        response = self.client.get(reverse("cme_dashboard"))

        self.assertContains(response, 'type="date"')


class MovimentacoesFiltroPeriodoVisivelTests(TestCase):
    """O filtro de período de Movimentações (item 11 da avaliação visual)
    virou campo editável na própria tela — antes só chegava como hidden pela
    URL (ex.: vindo de um KPI da Visão Geral), sem controle direto aqui."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-mov-periodo", password="senha-segura"
        )
        self.client.force_login(self.usuario)

    def test_formulario_traz_campos_de_data_visiveis(self) -> None:
        response = self.client.get(reverse("cme_home"))

        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'name="data_inicio"')
        self.assertContains(response, 'name="data_fim"')
        self.assertNotContains(response, 'type="hidden" name="data_inicio"')
        self.assertNotContains(response, 'type="hidden" name="data_fim"')

    def test_campos_preenchidos_quando_filtro_vem_pela_url(self) -> None:
        response = self.client.get(
            reverse("cme_home"),
            {"data_inicio": "2026-01-01", "data_fim": "2026-06-30"},
        )

        self.assertContains(response, 'value="2026-01-01"')
        self.assertContains(response, 'value="2026-06-30"')
        self.assertNotContains(response, "dd/mm/aaaa")


class MovimentacoesRotulosContagemTests(TestCase):
    """Rótulo de contagem ao lado de "N registros" em Movimentações (item 12
    da avaliação visual) — só faz sentido quando o status selecionado é o
    mesmo que ele descreve; com "todos" ele não tem relação com a listagem
    exibida e era só ruído."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="cme-rotulos", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno_nome="Aluno Pendente",
            pacote_codigo="ROT-1",
            retirado=False,
            arquivo_origem="painel",
            row_hash="hash-rotulo-pendente",
            origem=OrigemDados.MANUAL,
        )
        Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno_nome="Aluno Retirado",
            pacote_codigo="ROT-2",
            retirado=True,
            arquivo_origem="painel",
            row_hash="hash-rotulo-retirado",
            origem=OrigemDados.MANUAL,
        )

    def test_status_todos_nao_mostra_nenhum_rotulo(self) -> None:
        response = self.client.get(reverse("cme_home"))

        self.assertNotContains(response, "aguardando retirada")
        self.assertNotContains(response, "retirado</span>")

    def test_status_pendente_mostra_aguardando_retirada(self) -> None:
        response = self.client.get(reverse("cme_home"), {"status": "pendente"})

        self.assertContains(response, "aguardando retirada")
        self.assertContains(response, "<strong>1</strong> aguardando retirada")

    def test_status_retirado_mostra_rotulo_de_retirado(self) -> None:
        response = self.client.get(reverse("cme_home"), {"status": "retirado"})

        self.assertNotContains(response, "aguardando retirada")
        self.assertContains(response, "<strong>1</strong> retirado</span>")
