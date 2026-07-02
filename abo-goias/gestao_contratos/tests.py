"""Testes da aplicação de gestão de contratos.

Cobre views, serviço de checklist e integração com o Dental Office.
Prioridade: views e integração Dental → checklist service → models.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from gestao_contratos.models import ContratoGerado
from gestao_contratos.services.checklist import (
    gerar_checklist,
    pendencias_obrigatorias,
)
from gestao_contratos.services.documentos import gerar_e_salvar_contrato
from gestao_lab.integrations.dental import DentalAPIError
from gestao_lab.models import Paciente

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usuario(username: str = "coord") -> User:
    return User.objects.create_user(username=username, password="senha-segura")


def _paciente(**kwargs) -> Paciente:
    defaults = {"nome": "Paciente Teste", "id_dental": "999"}
    defaults.update(kwargs)
    return Paciente.objects.create(**defaults)


def _paciente_completo(**kwargs) -> Paciente:
    """Paciente com todos os dados necessários para gerar contrato."""
    defaults = {
        "nome": "João da Silva",
        "id_dental": "888",
        "cpf": "123.456.789-00",
        "data_nascimento": date(1990, 5, 15),
        "endereco_logradouro": "Rua das Flores",
        "endereco_cidade": "Goiânia",
        "endereco_estado": "GO",
    }
    defaults.update(kwargs)
    return Paciente.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Testes de Models
# ---------------------------------------------------------------------------


class ContratoGeradoModelTests(TestCase):
    def test_str_inclui_tipo_paciente_e_data(self) -> None:
        usuario = _usuario()
        pac = _paciente_completo()
        contrato = ContratoGerado.objects.create(
            paciente=pac,
            tipo="modelo_1",
            gerado_por=usuario,
        )
        texto = str(contrato)
        self.assertIn("Modelo 1", texto)
        self.assertIn("João da Silva", texto)

    def test_ordering_mais_recente_primeiro(self) -> None:
        usuario = _usuario()
        pac = _paciente_completo()
        c1 = ContratoGerado.objects.create(
            paciente=pac, tipo="modelo_1", gerado_por=usuario
        )
        c2 = ContratoGerado.objects.create(
            paciente=pac, tipo="modelo_2", gerado_por=usuario
        )
        contratos = list(ContratoGerado.objects.all())
        self.assertEqual(contratos[0], c2)
        self.assertEqual(contratos[1], c1)


# ---------------------------------------------------------------------------
# Testes do serviço de checklist
# ---------------------------------------------------------------------------


class ChecklistPacienteMaiorTests(TestCase):
    """Paciente adulto — responsável é opcional."""

    def _pac_completo(self) -> Paciente:
        return _paciente_completo(id_dental="C1")

    def test_checklist_sem_pendencias_quando_dados_completos(self) -> None:
        pac = self._pac_completo()
        itens = gerar_checklist(pac)
        pendentes = [i for i in itens if i.status == "pendente"]
        self.assertEqual(pendentes, [])

    def test_checklist_com_pendencia_sem_documento(self) -> None:
        pac = _paciente(
            id_dental="C2",
            data_nascimento=date(1990, 1, 1),
            endereco_cidade="Goiânia",
        )
        itens = gerar_checklist(pac)
        rotulos_pendentes = [i.rotulo for i in itens if i.status == "pendente"]
        self.assertIn("Documento (CPF ou RG)", rotulos_pendentes)

    def test_checklist_com_pendencia_sem_cidade(self) -> None:
        pac = _paciente(id_dental="C3", cpf="111.222.333-44")
        itens = gerar_checklist(pac)
        rotulos_pendentes = [i.rotulo for i in itens if i.status == "pendente"]
        self.assertIn("Cidade/Endereço", rotulos_pendentes)

    def test_responsavel_opcional_para_maior_de_idade(self) -> None:
        pac = _paciente_completo(id_dental="C4")
        itens = gerar_checklist(pac)
        item_resp = next(
            (i for i in itens if "Responsável" in i.rotulo and "nome" in i.rotulo), None
        )
        self.assertIsNotNone(item_resp)
        self.assertFalse(item_resp.obrigatorio)

    def test_rg_aceito_como_documento(self) -> None:
        pac = _paciente(
            id_dental="C5",
            rg="1234567",
            data_nascimento=date(1990, 1, 1),
            endereco_cidade="Goiânia",
        )
        pendencias = pendencias_obrigatorias(pac)
        self.assertEqual(pendencias, [])


class ChecklistPacienteMenorTests(TestCase):
    """Paciente menor de idade — responsável é obrigatório."""

    def _pac_menor(self, **kwargs) -> Paciente:
        hoje = date.today()
        nascimento = date(hoje.year - 10, hoje.month, hoje.day)
        defaults = {
            "id_dental": "M1",
            "cpf": "111.222.333-44",
            "data_nascimento": nascimento,
            "endereco_cidade": "Goiânia",
        }
        defaults.update(kwargs)
        return _paciente(**defaults)

    def test_responsavel_obrigatorio_para_menor(self) -> None:
        pac = self._pac_menor()
        itens = gerar_checklist(pac)
        item_resp = next(
            (i for i in itens if "Responsável" in i.rotulo and "nome" in i.rotulo), None
        )
        self.assertIsNotNone(item_resp)
        self.assertTrue(item_resp.obrigatorio)

    def test_pendencias_incluem_responsavel_sem_dados(self) -> None:
        pac = self._pac_menor()
        pendencias = pendencias_obrigatorias(pac)
        rotulos = [p.rotulo for p in pendencias]
        self.assertIn("Responsável legal — nome", rotulos)
        self.assertIn("Responsável legal — CPF", rotulos)

    def test_sem_pendencias_com_responsavel_preenchido(self) -> None:
        hoje = date.today()
        nascimento = date(hoje.year - 10, hoje.month, hoje.day)
        pac = _paciente(
            id_dental="M2",
            cpf="111.222.333-44",
            data_nascimento=nascimento,
            endereco_cidade="Goiânia",
            nome_responsavel="Mãe da Paciente",
            cpf_responsavel="999.888.777-66",
        )
        pendencias = pendencias_obrigatorias(pac)
        self.assertEqual(pendencias, [])


class PendenciasObrigatoriasTests(TestCase):
    def test_retorna_lista_vazia_quando_dados_completos(self) -> None:
        pac = _paciente_completo(id_dental="P1")
        self.assertEqual(pendencias_obrigatorias(pac), [])

    def test_retorna_apenas_itens_obrigatorios_pendentes(self) -> None:
        pac = _paciente(id_dental="P2", endereco_cidade="Goiânia")
        pendencias = pendencias_obrigatorias(pac)
        self.assertTrue(all(p.obrigatorio for p in pendencias))
        self.assertTrue(all(p.status == "pendente" for p in pendencias))


# ---------------------------------------------------------------------------
# Testes de Views — autenticação
# ---------------------------------------------------------------------------


class AutenticacaoContratosTests(TestCase):
    def _assert_redireciona(self, url: str) -> None:
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={url}',
            fetch_redirect_response=False,
        )

    def test_contratos_exige_login(self) -> None:
        self._assert_redireciona(reverse("contratos"))

    def test_gerar_contrato_exige_login(self) -> None:
        pac = _paciente_completo()
        self._assert_redireciona(reverse("contrato_gerar", args=[pac.pk]))

    def test_importar_e_gerar_exige_login(self) -> None:
        self._assert_redireciona(reverse("contrato_importar", args=["123"]))


# ---------------------------------------------------------------------------
# Testes de Views — listagem de contratos
# ---------------------------------------------------------------------------


class ContratosViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("contratos"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/contratos.html")

    def test_lista_pacientes_ativos(self) -> None:
        _paciente(nome="Carlos Ativo", id_dental="A1")
        _paciente(nome="Ana Inativa", id_dental="A2", ativo=False)
        response = self.client.get(reverse("contratos"))
        self.assertContains(response, "Carlos Ativo")
        self.assertNotContains(response, "Ana Inativa")

    def test_busca_filtra_pacientes_por_nome(self) -> None:
        _paciente(nome="Fernanda Lima", id_dental="A3")
        _paciente(nome="Roberto Souza", id_dental="A4")
        response = self.client.get(reverse("contratos"), {"q": "Fernanda"})
        self.assertContains(response, "Fernanda Lima")
        self.assertNotContains(response, "Roberto Souza")

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_sem_resultado_local_busca_na_api(self, MockDental: MagicMock) -> None:
        mock_client = MockDental.return_value
        mock_client.listar_pacientes.return_value = {
            "results": [
                {
                    "id": 55,
                    "name": "Patricia API",
                    "active": True,
                    "contacts_attributes": [],
                }
            ]
        }

        response = self.client.get(reverse("contratos"), {"q": "Patricia"})

        self.assertEqual(response.status_code, 200)
        pacientes_api = response.context["pacientes_api"]
        nomes = [p["nome"] for p in pacientes_api]
        self.assertIn("Patricia API", nomes)

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_erro_na_api_exibe_mensagem(self, MockDental: MagicMock) -> None:
        MockDental.return_value.listar_pacientes.side_effect = DentalAPIError(
            "API fora do ar"
        )

        response = self.client.get(reverse("contratos"), {"q": "Ninguem"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "API fora do ar")

    @override_settings(DENTAL_CLINIC_ID=None)
    def test_sem_clinic_id_configurado_exibe_aviso(self) -> None:
        response = self.client.get(reverse("contratos"), {"q": "Teste"})
        self.assertContains(response, "DENTAL_CLINIC_ID")

    def test_busca_vazia_nao_consulta_api(self) -> None:
        _paciente(nome="Alguem Local", id_dental="A5")
        with patch("gestao_contratos.views.DentalClient") as MockDental:
            response = self.client.get(reverse("contratos"))
            MockDental.assert_not_called()
        self.assertEqual(response.status_code, 200)

    def test_resultado_local_encontrado_nao_consulta_api(self) -> None:
        _paciente(nome="Marcos Local", id_dental="A6")
        with patch("gestao_contratos.views.DentalClient") as MockDental:
            response = self.client.get(reverse("contratos"), {"q": "Marcos"})
            MockDental.assert_not_called()
        self.assertContains(response, "Marcos Local")


# ---------------------------------------------------------------------------
# Testes de Views — importar e gerar
# ---------------------------------------------------------------------------


class ImportarEGerarViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def _dados_api(self, **kwargs) -> dict:
        base = {
            "name": "Novo Paciente",
            "active": True,
            "contacts_attributes": [{"cellphone": "(62) 99999-0000"}],
            "cpf": "111.222.333-44",
            "rg": "",
            "born_at": "1990-05-10",
            "address_attributes": {
                "address": "Rua A",
                "number": "100",
                "complement": "",
                "neighborhood": "Centro",
                "city": "Goiânia",
                "state": "GO",
                "zip_code": "74000-000",
            },
        }
        base.update(kwargs)
        return base

    @patch("gestao_contratos.views.DentalClient")
    def test_importa_novo_paciente_e_redireciona(self, MockDental: MagicMock) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = (
            self._dados_api()
        )

        response = self.client.get(reverse("contrato_importar", args=["77"]))

        self.assertTrue(Paciente.objects.filter(id_dental="77").exists())
        pac = Paciente.objects.get(id_dental="77")
        self.assertRedirects(
            response,
            reverse("contrato_gerar", args=[pac.pk]),
            fetch_redirect_response=False,
        )

    @patch("gestao_contratos.views.DentalClient")
    def test_atualiza_paciente_existente(self, MockDental: MagicMock) -> None:
        pac_existente = _paciente(id_dental="88", nome="Nome Antigo")
        MockDental.return_value.buscar_detalhes_paciente.return_value = self._dados_api(
            name="Nome Atualizado"
        )

        self.client.get(reverse("contrato_importar", args=["88"]))

        pac_existente.refresh_from_db()
        self.assertEqual(pac_existente.nome, "Nome Atualizado")

    @patch("gestao_contratos.views.DentalClient")
    def test_erro_api_redireciona_com_mensagem(self, MockDental: MagicMock) -> None:
        MockDental.return_value.buscar_detalhes_paciente.side_effect = DentalAPIError(
            "conexão recusada"
        )

        response = self.client.get(
            reverse("contrato_importar", args=["99"]), follow=True
        )

        self.assertRedirects(response, reverse("contratos"))
        self.assertContains(response, "conexão recusada")

    @patch("gestao_contratos.views.DentalClient")
    def test_nome_vazio_redireciona_com_erro(self, MockDental: MagicMock) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {"name": ""}

        response = self.client.get(
            reverse("contrato_importar", args=["111"]), follow=True
        )

        self.assertRedirects(response, reverse("contratos"))
        self.assertFalse(Paciente.objects.filter(id_dental="111").exists())


# ---------------------------------------------------------------------------
# Testes de Views — gerar contrato (GET)
# ---------------------------------------------------------------------------


class GerarContratoGetTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    @patch("gestao_contratos.views.DentalClient")
    def test_retorna_200_e_template_correto(self, MockDental: MagicMock) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Paciente Ok",
            "active": True,
            "contacts_attributes": [],
            "cpf": "123.456.789-00",
            "address_attributes": {"city": "Goiânia", "state": "GO"},
        }
        pac = _paciente_completo(id_dental="200")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/gerar_contrato.html")

    def test_paciente_inexistente_retorna_404(self) -> None:
        response = self.client.get(reverse("contrato_gerar", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_paciente_inativo_retorna_404(self) -> None:
        pac = _paciente(id_dental="201", ativo=False)
        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))
        self.assertEqual(response.status_code, 404)

    @patch("gestao_contratos.views.DentalClient")
    def test_checklist_exibido_no_contexto(self, MockDental: MagicMock) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Joao Silva",
            "active": True,
            "contacts_attributes": [],
            "cpf": "123.456.789-00",
            "address_attributes": {"city": "Goiânia", "state": "GO"},
        }
        pac = _paciente_completo(id_dental="202")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertIn("checklist", response.context)
        self.assertIn("pendencias", response.context)

    @patch("gestao_contratos.views.DentalClient")
    def test_sincronizacao_forcada_exibe_mensagem_sucesso(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Sincronizado",
            "active": True,
            "contacts_attributes": [],
            "cpf": "321.654.987-00",
            "address_attributes": {"city": "Anápolis", "state": "GO"},
        }
        pac = _paciente_completo(id_dental="203")

        response = self.client.get(
            reverse("contrato_gerar", args=[pac.pk]) + "?sincronizar=1",
            follow=True,
        )

        self.assertContains(response, "Dados atualizados")

    @patch("gestao_contratos.views.DentalClient")
    def test_erro_dental_na_sync_exibe_aviso_sem_quebrar(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.side_effect = DentalAPIError(
            "timeout"
        )
        # Paciente incompleto (sem CPF e sem cidade) dispara sync automático
        pac = _paciente(id_dental="204")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "timeout")


# ---------------------------------------------------------------------------
# Testes de Views — gerar contrato (POST)
# ---------------------------------------------------------------------------


class GerarContratoPostTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def _dados_post(self, **kwargs) -> dict:
        base = {
            "tipo": "modelo_1",
            "observacoes_clinicas": "Sem intercorrências.",
            "profissional_nome": "Dr. Teste",
            "profissional_cro": "CRO-GO 1234",
            "local_assinatura": "Goiânia - GO",
        }
        base.update(kwargs)
        return base

    @patch("gestao_contratos.views.DentalClient")
    def test_post_com_pendencias_redireciona_com_erro(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Incompleto",
            "active": True,
            "contacts_attributes": [],
        }
        pac = _paciente(id_dental="300")

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(),
            follow=True,
        )

        self.assertContains(response, "dados obrigatórios ausentes")
        self.assertEqual(ContratoGerado.objects.count(), 0)

    @patch("gestao_contratos.views.gerar_e_salvar_contrato")
    @patch("gestao_contratos.views.DentalClient")
    def test_post_valido_registra_contrato_e_redireciona(
        self, MockDental: MagicMock, mock_gerar: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Joao Completo",
            "active": True,
            "contacts_attributes": [],
            "cpf": "123.456.789-00",
            "address_attributes": {"city": "Goiânia", "state": "GO"},
        }
        pac = _paciente_completo(id_dental="301")
        contrato = ContratoGerado.objects.create(
            paciente=pac, tipo="modelo_1", gerado_por=self.usuario
        )
        mock_gerar.return_value = contrato

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(),
        )

        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[contrato.pk]),
            fetch_redirect_response=False,
        )
        mock_gerar.assert_called_once()
        kwargs = mock_gerar.call_args.kwargs
        self.assertEqual(kwargs["tipo"], "modelo_1")
        self.assertEqual(kwargs["paciente"], pac)
        self.assertEqual(kwargs["gerado_por"], self.usuario)

    @patch("gestao_contratos.views.DentalClient")
    def test_post_com_tipo_invalido_redireciona_com_erro(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "name": "Joao",
            "active": True,
            "contacts_attributes": [],
            "cpf": "123.456.789-00",
            "address_attributes": {"city": "Goiânia", "state": "GO"},
        }
        pac = _paciente_completo(id_dental="302")

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(tipo="tipo_invalido"),
            follow=True,
        )

        self.assertContains(response, "tipo de contrato válido")
        self.assertEqual(ContratoGerado.objects.count(), 0)


# ---------------------------------------------------------------------------
# Testes do serviço de geração — ciclo de vida (Fase 0)
# ---------------------------------------------------------------------------


class GerarESalvarContratoTests(TestCase):
    """Cobre status inicial, versionamento e hash SHA-256 do PDF."""

    def setUp(self) -> None:
        self.usuario = _usuario()
        self.pac = _paciente_completo(id_dental="400")
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def _gerar(self, tipo: str = "modelo_1") -> ContratoGerado:
        return gerar_e_salvar_contrato(
            paciente=self.pac,
            tipo=tipo,
            gerado_por=self.usuario,
        )

    def test_salva_docx_e_pdf(self) -> None:
        contrato = self._gerar()
        self.assertTrue(contrato.arquivo.name.endswith(".docx"))
        self.assertTrue(contrato.arquivo_pdf.name.endswith(".pdf"))

    def test_status_inicial_gerado(self) -> None:
        contrato = self._gerar()
        self.assertEqual(contrato.status, "gerado")

    def test_hash_sha256_corresponde_ao_pdf_salvo(self) -> None:
        contrato = self._gerar()
        contrato.arquivo_pdf.open("rb")
        conteudo = contrato.arquivo_pdf.read()
        contrato.arquivo_pdf.close()
        self.assertEqual(len(contrato.hash_sha256), 64)
        self.assertEqual(contrato.hash_sha256, hashlib.sha256(conteudo).hexdigest())

    def test_versao_incrementa_por_paciente_e_tipo(self) -> None:
        c1 = self._gerar()
        c2 = self._gerar()
        c3 = self._gerar(tipo="modelo_2")
        self.assertEqual(c1.versao, 1)
        self.assertEqual(c2.versao, 2)
        self.assertEqual(c3.versao, 1)

    def test_versao_independente_por_paciente(self) -> None:
        self._gerar()
        outro = _paciente_completo(id_dental="401")
        contrato_outro = gerar_e_salvar_contrato(
            paciente=outro, tipo="modelo_1", gerado_por=self.usuario
        )
        self.assertEqual(contrato_outro.versao, 1)
