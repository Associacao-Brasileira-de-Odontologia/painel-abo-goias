"""Testes da aplicação de gestão de contratos.

Cobre views, serviço de checklist e integração com o Dental Office.
Prioridade: views e integração Dental → checklist service → models.
"""

from __future__ import annotations

import base64
import hashlib
import io
import tempfile
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from gestao_contratos.models import ContratoGerado, EventoContrato, SessaoAssinatura
from gestao_contratos.services.assinatura import (
    AssinaturaInvalida,
    SessaoInvalida,
    criar_sessao,
    expirar_sessoes_globalmente,
    gerar_token,
    processar_assinatura,
    resolver_token,
    sessao_ativa,
)
from gestao_contratos.services.checklist import (
    gerar_checklist,
    pendencias_obrigatorias,
)
from gestao_contratos.services.documentos import gerar_e_salvar_contrato
from gestao_contratos.tasks import enviar_dental_task, expirar_sessoes_vencidas_task
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
    """Paciente com dados completos e confirmados — pronto para gerar contrato."""
    defaults = {
        "nome": "João da Silva",
        "id_dental": "888",
        "cpf": "123.456.789-00",
        "data_nascimento": date(1990, 5, 15),
        "endereco_logradouro": "Rua das Flores",
        "endereco_cidade": "Goiânia",
        "endereco_estado": "GO",
        "dados_confirmados_em": timezone.now(),
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

    def test_confirmar_dados_exige_login(self) -> None:
        pac = _paciente_completo()
        self._assert_redireciona(reverse("contrato_confirmar_dados", args=[pac.pk]))

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

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_busca_explicita_consulta_api_mesmo_com_resultado_local(
        self, MockDental: MagicMock
    ) -> None:
        _paciente(nome="Helena Local", id_dental="A7")
        mock_client = MockDental.return_value
        mock_client.listar_pacientes.return_value = {
            "results": [
                {
                    "id": 77,
                    "name": "Helena Dental",
                    "active": True,
                    "contacts_attributes": [],
                }
            ]
        }

        response = self.client.get(reverse("contratos"), {"q": "Helena", "dental": "1"})

        mock_client.listar_pacientes.assert_called_once()
        self.assertContains(response, "Helena Local")
        self.assertContains(response, "Helena Dental")


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
            reverse("contrato_confirmar_dados", args=[pac.pk]),
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

    def test_retorna_200_e_template_correto(self) -> None:
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

    def test_checklist_exibido_no_contexto(self) -> None:
        pac = _paciente_completo(id_dental="202")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertIn("checklist", response.context)
        self.assertIn("pendencias", response.context)

    def test_paciente_nao_confirmado_redireciona_para_confirmacao(self) -> None:
        pac = _paciente_completo(id_dental="205", dados_confirmados_em=None)

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertRedirects(
            response,
            reverse("contrato_confirmar_dados", args=[pac.pk]),
            fetch_redirect_response=False,
        )


# ---------------------------------------------------------------------------
# Testes de Views — confirmação de dados
# ---------------------------------------------------------------------------


class ConfirmarDadosViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def _dados_form(self, paciente: Paciente, **kwargs) -> dict:
        base = {
            "nome": paciente.nome,
            "cpf": paciente.cpf,
            "rg": paciente.rg,
            "data_nascimento": (
                paciente.data_nascimento.isoformat() if paciente.data_nascimento else ""
            ),
            "celular": paciente.celular,
            "email": paciente.email,
            "convenio": paciente.convenio,
            "endereco_logradouro": paciente.endereco_logradouro,
            "endereco_numero": paciente.endereco_numero,
            "endereco_complemento": paciente.endereco_complemento,
            "endereco_bairro": paciente.endereco_bairro,
            "endereco_cidade": paciente.endereco_cidade,
            "endereco_estado": paciente.endereco_estado,
            "endereco_cep": paciente.endereco_cep,
            "nome_responsavel": paciente.nome_responsavel,
            "cpf_responsavel": paciente.cpf_responsavel,
        }
        base.update(kwargs)
        return base

    @patch("gestao_contratos.views.DentalClient")
    def test_get_retorna_200_sem_sincronizar_quando_completo(
        self, MockDental: MagicMock
    ) -> None:
        pac = _paciente_completo(id_dental="500")

        response = self.client.get(reverse("contrato_confirmar_dados", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/confirmar_dados.html")
        MockDental.assert_not_called()

    @patch("gestao_contratos.views.DentalClient")
    def test_get_sincroniza_quando_dados_incompletos(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "document_attributes": {"cpf": "98765432100"},
            "birth_date": "1985-03-10",
            "addresses_attributes": [
                {"street": "Rua Nova", "city": "Goiânia", "state": "GO"}
            ],
            "contacts_attributes": [],
        }
        pac = _paciente(id_dental="501")

        response = self.client.get(reverse("contrato_confirmar_dados", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        pac.refresh_from_db()
        self.assertEqual(pac.cpf, "987.654.321-00")
        self.assertEqual(pac.endereco_cidade, "Goiânia")

    @patch("gestao_contratos.views.DentalClient")
    def test_sincronizacao_forcada_limpa_confirmacao(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "document_attributes": {"cpf": "98765432100"},
            "addresses_attributes": [{"city": "Anápolis", "state": "GO"}],
            "contacts_attributes": [],
        }
        pac = _paciente_completo(id_dental="502", convenio="Unimed")

        response = self.client.get(
            reverse("contrato_confirmar_dados", args=[pac.pk]) + "?sincronizar=1",
            follow=True,
        )

        self.assertContains(response, "Dados atualizados")
        pac.refresh_from_db()
        self.assertIsNone(pac.dados_confirmados_em)
        # Convênio é local — sincronização não pode sobrescrevê-lo.
        self.assertEqual(pac.convenio, "Unimed")

    @patch("gestao_contratos.views.DentalClient")
    def test_erro_dental_na_sync_exibe_aviso_sem_quebrar(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.side_effect = DentalAPIError(
            "timeout"
        )
        # Paciente incompleto (sem CPF e sem cidade) dispara sync automático
        pac = _paciente(id_dental="503")

        response = self.client.get(reverse("contrato_confirmar_dados", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "timeout")

    def test_post_salva_edicoes_e_confirma(self) -> None:
        pac = _paciente_completo(id_dental="504", dados_confirmados_em=None)

        response = self.client.post(
            reverse("contrato_confirmar_dados", args=[pac.pk]),
            data=self._dados_form(pac, convenio="Amil", celular="(62) 98888-7777"),
        )

        self.assertRedirects(
            response,
            reverse("contrato_gerar", args=[pac.pk]),
            fetch_redirect_response=False,
        )
        pac.refresh_from_db()
        self.assertEqual(pac.convenio, "Amil")
        self.assertEqual(pac.celular, "(62) 98888-7777")
        self.assertIsNotNone(pac.dados_confirmados_em)
        self.assertEqual(pac.dados_confirmados_por, self.usuario)

    def test_post_sem_nome_reexibe_formulario(self) -> None:
        pac = _paciente_completo(id_dental="505", dados_confirmados_em=None)

        response = self.client.post(
            reverse("contrato_confirmar_dados", args=[pac.pk]),
            data=self._dados_form(pac, nome=""),
        )

        self.assertEqual(response.status_code, 200)
        pac.refresh_from_db()
        self.assertIsNone(pac.dados_confirmados_em)


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
        # Confirmado porém incompleto — o checklist deve barrar a geração.
        pac = _paciente(id_dental="300", dados_confirmados_em=timezone.now())

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


# ---------------------------------------------------------------------------
# Testes de assinatura remota (Fase 2)
# ---------------------------------------------------------------------------


def _assinatura_data_url() -> str:
    """PNG realista de assinatura, como o canvas enviaria (data URL)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)
    desenho.line(
        [(10, 60), (80, 30), (150, 70), (280, 40)], fill=(20, 38, 62, 255), width=4
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class AssinaturaBaseTests(TestCase):
    """Base: contrato real (com PDF) em MEDIA_ROOT temporário.

    ``enviar_dental_task.delay`` é mockado aqui porque, em CELERY_TASK_ALWAYS_EAGER
    (ativo durante os testes), qualquer chamada real executaria a tarefa
    de forma síncrona — incluindo uma tentativa de rede à API real do
    Dental Office, já que este projeto tem um .env com credenciais válidas.
    O comportamento real da tarefa é coberto isoladamente em
    EnviarDentalTaskTests, que não herda desta base.
    """

    def setUp(self) -> None:
        cache.clear()
        self.usuario = _usuario()
        self.client.force_login(self.usuario)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="600")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )

        patcher = patch("gestao_contratos.tasks.enviar_dental_task.delay")
        self.mock_enviar_dental_delay = patcher.start()
        self.addCleanup(patcher.stop)


class SessaoAssinaturaServiceTests(AssinaturaBaseTests):
    def test_criar_sessao_define_estado_e_evento(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        self.assertEqual(sessao.status, "pendente")
        self.assertGreater(sessao.expira_em, timezone.now())
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "aguardando_assinatura")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="sessao_criada"
            ).exists()
        )

    def test_criar_nova_sessao_cancela_anterior(self) -> None:
        antiga = criar_sessao(self.contrato, criado_por=self.usuario)
        nova = criar_sessao(self.contrato, criado_por=self.usuario)

        antiga.refresh_from_db()
        self.assertEqual(antiga.status, "cancelada")
        self.assertEqual(nova.status, "pendente")
        self.assertEqual(sessao_ativa(self.contrato), nova)

    def test_resolver_token_valido(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        resolvida = resolver_token(gerar_token(sessao))
        self.assertEqual(resolvida.pk, sessao.pk)

    def test_resolver_token_adulterado_invalido(self) -> None:
        with self.assertRaises(SessaoInvalida) as ctx:
            resolver_token("token-adulterado")
        self.assertEqual(ctx.exception.motivo, "invalida")

    def test_resolver_token_sessao_expirada(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        sessao.expira_em = timezone.now() - timezone.timedelta(minutes=1)
        sessao.save(update_fields=["expira_em"])

        with self.assertRaises(SessaoInvalida) as ctx:
            resolver_token(gerar_token(sessao))

        self.assertEqual(ctx.exception.motivo, "expirada")
        sessao.refresh_from_db()
        self.assertEqual(sessao.status, "expirada")
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=sessao, tipo="sessao_expirada"
            ).exists()
        )

    def test_resolver_token_sessao_cancelada(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        criar_sessao(self.contrato, criado_por=self.usuario)  # cancela a antiga

        with self.assertRaises(SessaoInvalida) as ctx:
            resolver_token(token)
        self.assertEqual(ctx.exception.motivo, "cancelada")


class ProcessarAssinaturaTests(AssinaturaBaseTests):
    def test_assinatura_valida_gera_pdf_assinado(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        hash_original = self.contrato.hash_sha256

        processar_assinatura(
            sessao,
            _assinatura_data_url(),
            ip="203.0.113.10",
            user_agent="TesteAgente/1.0",
        )

        self.contrato.refresh_from_db()
        sessao.refresh_from_db()

        self.assertEqual(self.contrato.status, "assinado")
        self.assertTrue(self.contrato.arquivo_pdf_assinado.name.endswith(".pdf"))
        self.contrato.arquivo_pdf_assinado.open("rb")
        conteudo = self.contrato.arquivo_pdf_assinado.read()
        self.contrato.arquivo_pdf_assinado.close()
        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertNotEqual(self.contrato.hash_sha256, hash_original)
        self.assertEqual(
            self.contrato.hash_sha256, hashlib.sha256(conteudo).hexdigest()
        )

        self.assertEqual(sessao.status, "assinada")
        self.assertEqual(sessao.ip_assinatura, "203.0.113.10")
        self.assertEqual(sessao.user_agent, "TesteAgente/1.0")
        self.assertTrue(sessao.assinatura_imagem.name)

        tipos = set(
            EventoContrato.objects.filter(contrato=self.contrato).values_list(
                "tipo", flat=True
            )
        )
        self.assertIn("assinatura_concluida", tipos)
        self.assertIn("documento_assinado_salvo", tipos)

    def test_segunda_assinatura_rejeitada(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        processar_assinatura(
            sessao, _assinatura_data_url(), ip="203.0.113.10", user_agent="X"
        )

        with self.assertRaises(SessaoInvalida) as ctx:
            processar_assinatura(
                sessao, _assinatura_data_url(), ip="203.0.113.11", user_agent="Y"
            )
        self.assertEqual(ctx.exception.motivo, "ja_assinada")

    def test_imagem_invalida_rejeitada_sem_consumir_sessao(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        with self.assertRaises(AssinaturaInvalida):
            processar_assinatura(
                sessao, "data:image/png;base64,bm90cG5n", ip=None, user_agent=""
            )

        sessao.refresh_from_db()
        self.assertEqual(sessao.status, "pendente")
        self.assertIsNotNone(sessao_ativa(self.contrato))

    def test_assinatura_concluida_agenda_envio_ao_dental(self) -> None:
        """Fase 4: assinar deve enfileirar enviar_dental_task com o pk do contrato."""
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_dental_delay.assert_called_once_with(self.contrato.pk)

    def test_assinatura_sem_id_dental_nao_agenda_envio(self) -> None:
        """Sem id_dental, não há como enviar — a tarefa não deve ser enfileirada."""
        self.pac.id_dental = ""
        self.pac.save(update_fields=["id_dental"])
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_dental_delay.assert_not_called()

    def test_falha_ao_enfileirar_nao_quebra_a_assinatura(self) -> None:
        """Regressão: broker/Redis indisponível não pode derrubar a assinatura.

        Reproduz o bug relatado em produção — .delay() lançando exceção
        (ex.: Redis inacessível) não pode impedir que a assinatura do
        paciente seja salva com sucesso.
        """
        self.mock_enviar_dental_delay.side_effect = RuntimeError(
            "Retry limit exceeded while trying to reconnect to the Celery "
            "result store backend. The Celery application must be restarted."
        )
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        contrato = processar_assinatura(
            sessao, _assinatura_data_url(), ip=None, user_agent=""
        )

        self.assertEqual(contrato.status, "assinado")
        self.assertTrue(contrato.arquivo_pdf_assinado.name)
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=contrato, tipo="envio_dental_erro"
            ).exists()
        )


class AssinaturaPublicaViewTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        self.sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        self.token = gerar_token(self.sessao)
        self.url = reverse("assinatura_publica", args=[self.token])

    def test_get_nao_exige_login(self) -> None:
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")

    def test_get_marca_sessao_como_aberta(self) -> None:
        self.client.logout()
        self.client.get(self.url)
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.status, "aberta")
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=self.sessao, tipo="contrato_aberto"
            ).exists()
        )

    def test_get_token_invalido_retorna_410(self) -> None:
        self.client.logout()
        response = self.client.get(
            reverse("assinatura_publica", args=["token-invalido"])
        )
        self.assertEqual(response.status_code, 410)

    def test_pdf_publico_acessivel(self) -> None:
        self.client.logout()
        response = self.client.get(reverse("assinatura_publica_pdf", args=[self.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_post_assina_e_exibe_confirmacao(self) -> None:
        self.client.logout()
        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "assinado")

    def test_acesso_apos_assinatura_retorna_410(self) -> None:
        self.client.logout()
        self.client.post(self.url, data={"assinatura": _assinatura_data_url()})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 410)

    def test_paciente_ve_confirmacao_mesmo_com_broker_indisponivel(self) -> None:
        """Regressão: o paciente não pode ver uma tela de erro por falha no
        Celery/Redis — a assinatura já foi salva e isso é o que importa
        para ele."""
        self.mock_enviar_dental_delay.side_effect = RuntimeError(
            "Retry limit exceeded while trying to reconnect to the Celery "
            "result store backend."
        )
        self.client.logout()

        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "assinado")

    def test_post_imagem_invalida_reexibe_pagina_com_erro(self) -> None:
        self.client.logout()
        response = self.client.post(self.url, data={"assinatura": "lixo"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")
        self.contrato.refresh_from_db()
        self.assertNotEqual(self.contrato.status, "assinado")


class AssinaturaStaffViewTests(AssinaturaBaseTests):
    def test_iniciar_assinatura_cria_sessao(self) -> None:
        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk])
        )

        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )
        self.assertIsNotNone(sessao_ativa(self.contrato))

    def test_qr_exige_login(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)
        self.client.logout()
        url = reverse("contrato_qr_assinatura", args=[self.contrato.pk])
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={url}',
            fetch_redirect_response=False,
        )

    def test_qr_retorna_png(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)
        response = self.client.get(
            reverse("contrato_qr_assinatura", args=[self.contrato.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_qr_sem_sessao_ativa_retorna_404(self) -> None:
        response = self.client.get(
            reverse("contrato_qr_assinatura", args=[self.contrato.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_cancelar_sessao_restaura_status(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)

        self.client.post(
            reverse("contrato_cancelar_assinatura", args=[self.contrato.pk])
        )

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "gerado")
        self.assertIsNone(sessao_ativa(self.contrato))

    def test_baixar_assinado_apos_assinatura(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        response = self.client.get(
            reverse("contrato_baixar_assinado", args=[self.contrato.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_baixar_assinado_sem_assinatura_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_baixar_assinado", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_pos_geracao_exibe_qr_quando_sessao_ativa(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)
        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )
        self.assertContains(response, "contratos/assinar/")
        self.assertContains(response, "Cancelar sessão de assinatura")


# ---------------------------------------------------------------------------
# Testes do polling de status em tempo real (Fase 3)
# ---------------------------------------------------------------------------


class StatusAssinaturaFragmentTests(AssinaturaBaseTests):
    def _url(self) -> str:
        return reverse("contrato_status_assinatura_fragment", args=[self.contrato.pk])

    def test_exige_login(self) -> None:
        self.client.logout()
        response = self.client.get(self._url())
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={self._url()}',
            fetch_redirect_response=False,
        )

    def test_retorna_fragmento_correto(self) -> None:
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "gestao_contratos/_status_assinatura_fragment.html"
        )
        # O fragmento não estende base.html — não deve haver <header> do app.
        self.assertNotContains(response, "<header")

    def test_inclui_hx_trigger_quando_aguardando_assinatura(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)
        response = self.client.get(self._url())
        self.assertContains(response, "hx-trigger")
        self.assertContains(response, "status-assinatura-section")

    def test_sem_hx_trigger_quando_assinado(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")
        response = self.client.get(self._url())
        self.assertNotContains(response, "hx-trigger")
        self.assertContains(response, "Baixar contrato assinado")

    def test_sem_hx_trigger_sem_sessao_ativa(self) -> None:
        response = self.client.get(self._url())
        self.assertNotContains(response, "hx-trigger")
        self.assertContains(response, "Gerar QR Code de assinatura")

    def test_exibe_timeline_de_eventos(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)
        response = self.client.get(self._url())
        self.assertContains(response, "Linha do tempo")
        self.assertContains(response, "Sessão de assinatura criada")

    def test_sessao_vencida_expira_e_contrato_volta_a_gerado(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        sessao.expira_em = timezone.now() - timezone.timedelta(minutes=1)
        sessao.save(update_fields=["expira_em"])

        response = self.client.get(self._url())

        sessao.refresh_from_db()
        self.contrato.refresh_from_db()
        self.assertEqual(sessao.status, "expirada")
        self.assertEqual(self.contrato.status, "gerado")
        self.assertNotContains(response, "hx-trigger")
        self.assertContains(response, "Gerar QR Code de assinatura")
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=sessao, tipo="sessao_expirada"
            ).exists()
        )

    def test_pos_geracao_para_de_pollar_apos_assinatura(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )
        self.assertContains(response, "hx-trigger")

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")
        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )
        self.assertNotContains(response, "hx-trigger")


class EnvioDentalEventosTests(AssinaturaBaseTests):
    """Cobre a instrumentação de EventoContrato no serviço de envio ao Dental."""

    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_sucesso_registra_eventos_iniciado_e_concluido(
        self, MockDental: MagicMock
    ) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.pac.id_dental = "600"
        MockDental.return_value.enviar_documento_paciente.return_value = {
            "id": 1,
            "message": "Document created successfully",
        }

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertTrue(ok)
        self.assertEqual(erro, "")
        tipos = list(
            EventoContrato.objects.filter(contrato=self.contrato).values_list(
                "tipo", flat=True
            )
        )
        self.assertIn("envio_dental_iniciado", tipos)
        self.assertIn("envio_dental_concluido", tipos)

    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_erro_da_api_registra_evento_de_erro(self, MockDental: MagicMock) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        MockDental.return_value.enviar_documento_paciente.side_effect = DentalAPIError(
            "indisponível"
        )

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertFalse(ok)
        evento = EventoContrato.objects.filter(
            contrato=self.contrato, tipo="envio_dental_erro"
        ).first()
        self.assertIsNotNone(evento)
        self.assertIn("indisponível", evento.payload.get("erro", ""))

    def test_sem_id_dental_registra_evento_de_erro(self) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.pac.id_dental = ""
        self.pac.save(update_fields=["id_dental"])

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertFalse(ok)
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="envio_dental_erro"
            ).exists()
        )

    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_prefere_pdf_assinado_quando_disponivel(
        self, MockDental: MagicMock
    ) -> None:
        """Regressão: o envio ao Dental Office enviava o PDF original (sem
        assinatura) mesmo quando o contrato já havia sido assinado."""
        from django.core.files.base import ContentFile
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.contrato.arquivo_pdf.open("rb")
        conteudo_original = self.contrato.arquivo_pdf.read()
        self.contrato.arquivo_pdf.close()

        # Simula o PDF já mesclado com a assinatura (bytes distintos do original).
        conteudo_assinado = conteudo_original + b"-ASSINADO"
        self.contrato.arquivo_pdf_assinado.save(
            "assinado.pdf", ContentFile(conteudo_assinado), save=True
        )

        MockDental.return_value.enviar_documento_paciente.return_value = {"id": 1}

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertTrue(ok)
        kwargs = MockDental.return_value.enviar_documento_paciente.call_args.kwargs
        self.assertEqual(kwargs["arquivo_bytes"], conteudo_assinado)
        self.assertIn("(assinado)", kwargs["nome"])

    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_usa_pdf_original_quando_ainda_nao_assinado(
        self, MockDental: MagicMock
    ) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.contrato.arquivo_pdf.open("rb")
        conteudo_original = self.contrato.arquivo_pdf.read()
        self.contrato.arquivo_pdf.close()

        MockDental.return_value.enviar_documento_paciente.return_value = {"id": 1}

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertTrue(ok)
        kwargs = MockDental.return_value.enviar_documento_paciente.call_args.kwargs
        self.assertEqual(kwargs["arquivo_bytes"], conteudo_original)
        self.assertNotIn("(assinado)", kwargs["nome"])


# ---------------------------------------------------------------------------
# Testes das tarefas Celery (Fase 4)
# ---------------------------------------------------------------------------


class EnviarDentalTaskTests(TestCase):
    """Testa enviar_dental_task diretamente — sem herdar de AssinaturaBaseTests,
    já que aquela base mocka justamente ``enviar_dental_task.delay`` para
    proteger os testes de assinatura de disparar a tarefa de verdade.
    """

    def setUp(self) -> None:
        self.usuario = _usuario()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="700")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )

    @patch("gestao_contratos.services.envio_dental.enviar_contrato_ao_dental")
    def test_sucesso_chama_uma_unica_vez(self, mock_enviar: MagicMock) -> None:
        mock_enviar.return_value = (True, "")

        enviar_dental_task.delay(self.contrato.pk)

        mock_enviar.assert_called_once_with(self.contrato)

    @patch("gestao_contratos.services.envio_dental.enviar_contrato_ao_dental")
    def test_recupera_apos_falha_temporaria(self, mock_enviar: MagicMock) -> None:
        mock_enviar.side_effect = [(False, "timeout"), (True, "")]

        enviar_dental_task.delay(self.contrato.pk)

        self.assertEqual(mock_enviar.call_count, 2)

    @patch("gestao_contratos.services.envio_dental.enviar_contrato_ao_dental")
    def test_falha_persistente_esgota_tentativas_sem_propagar(
        self, mock_enviar: MagicMock
    ) -> None:
        mock_enviar.return_value = (False, "Dental Office fora do ar")

        # .delay() é fire-and-forget — uma falha na tarefa nunca deve
        # estourar no código que a disparou (aqui, o próprio teste).
        enviar_dental_task.delay(self.contrato.pk)

        # 1 tentativa inicial + max_retries (5) configurados na tarefa.
        self.assertEqual(mock_enviar.call_count, 6)

    def test_contrato_inexistente_nao_chama_a_api(self) -> None:
        with patch(
            "gestao_contratos.services.envio_dental.enviar_contrato_ao_dental"
        ) as mock_enviar:
            enviar_dental_task.delay(999_999)
            mock_enviar.assert_not_called()


class ExpirarSessoesVencidasTaskTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="701")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )
        self.contrato.status = "aguardando_assinatura"
        self.contrato.save(update_fields=["status"])

    def test_expira_vencidas_e_ignora_validas(self) -> None:
        vencida = SessaoAssinatura.objects.create(
            contrato=self.contrato,
            expira_em=timezone.now() - timezone.timedelta(minutes=1),
        )

        outro_pac = _paciente_completo(id_dental="702")
        outro_contrato = gerar_e_salvar_contrato(
            paciente=outro_pac, tipo="modelo_1", gerado_por=self.usuario
        )
        valida = SessaoAssinatura.objects.create(
            contrato=outro_contrato,
            expira_em=timezone.now() + timezone.timedelta(minutes=30),
        )

        total = expirar_sessoes_globalmente()

        self.assertEqual(total, 1)
        vencida.refresh_from_db()
        valida.refresh_from_db()
        self.assertEqual(vencida.status, "expirada")
        self.assertEqual(valida.status, "pendente")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "gerado")
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=vencida, tipo="sessao_expirada"
            ).exists()
        )

    def test_sem_sessoes_vencidas_retorna_zero(self) -> None:
        SessaoAssinatura.objects.create(
            contrato=self.contrato,
            expira_em=timezone.now() + timezone.timedelta(minutes=30),
        )
        self.assertEqual(expirar_sessoes_globalmente(), 0)

    def test_task_delega_para_expirar_sessoes_globalmente(self) -> None:
        SessaoAssinatura.objects.create(
            contrato=self.contrato,
            expira_em=timezone.now() - timezone.timedelta(minutes=1),
        )

        resultado = expirar_sessoes_vencidas_task.delay()

        self.assertEqual(resultado.get(), 1)
