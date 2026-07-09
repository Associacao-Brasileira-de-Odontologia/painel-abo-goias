import json
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
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    OrigemDados,
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
        self.assertEqual(turma.observacoes, "Matriculas ativas no Eduq: 11")
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
