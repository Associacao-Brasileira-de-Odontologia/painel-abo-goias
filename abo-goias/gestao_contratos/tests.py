"""Testes da aplicação de gestão de contratos.

Cobre views, serviço de checklist e integração com o Dental Office.
Prioridade: views e integração Dental → checklist service → models.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from gestao_contratos.models import (
    TERMINAL_ATIVO_TTL_HORAS,
    ContratoGerado,
    EventoContrato,
    SessaoAssinatura,
    TerminalAssinatura,
    expirar_terminais_vencidos,
)
from gestao_contratos.services.assinatura import (
    LIMITE_TENTATIVAS_IDENTIDADE,
    AssinaturaInvalida,
    SessaoInvalida,
    _validar_png,
    confirmar_identidade,
    criar_sessao,
    eventos_recentes,
    expirar_sessoes_globalmente,
    gerar_token,
    processar_assinatura,
    resolver_token,
    sessao_ativa,
    sessao_ativa_para_terminal,
)
from gestao_contratos.services.carimbo_tempo import (
    carimbo_tempo_configurado,
    carregar_config_carimbo_tempo,
    solicitar_carimbo,
)
from gestao_contratos.services.checklist import (
    bloqueado,
    gerar_checklist,
    pendencias_obrigatorias,
)
from gestao_contratos.services.documentos import (
    gerar_contrato,
    gerar_e_salvar_contrato,
    gerar_pdf,
)
from gestao_contratos.services.envio import normalizar_celular
from gestao_contratos.services.validacao import ArquivoInvalido, validar_pdf
from gestao_contratos.services.whatsapp import enviar_whatsapp_contrato
from gestao_contratos.tasks import (
    enviar_dental_task,
    enviar_whatsapp_task,
    expirar_sessoes_vencidas_task,
    solicitar_carimbo_tempo_task,
)
from gestao_lab.integrations.dental import DentalAPIError
from gestao_lab.models import Paciente
from mensageria import MessagingResult
from mensageria.exceptions import (
    InstanceDisconnectedError,
    InvalidRecipientError,
    MessageRejectedError,
    MessagingAuthenticationError,
    MessagingError,
    MessagingTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
)
from mensageria.validators import validar_destinatario
from mensageria.zapi import ZApiProvider, carregar_config_zapi

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
    """Paciente adulto — responsável nem aparece no checklist (o campo fica
    oculto na tela para quem é maior de idade)."""

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

    def test_responsavel_ausente_do_checklist_para_maior_de_idade(self) -> None:
        pac = _paciente_completo(id_dental="C4")
        itens = gerar_checklist(pac)
        item_resp = next(
            (i for i in itens if "Responsável" in i.rotulo and "nome" in i.rotulo), None
        )
        self.assertIsNone(item_resp)

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

    def test_barra_lateral_tem_link_de_validacao(self) -> None:
        # A listagem de pacientes deve herdar a barra lateral do base.html,
        # incluindo o link "Validar documento" — sem sobrescrever o bloco.
        response = self.client.get(reverse("contratos"))
        self.assertContains(response, "Validar documento")
        self.assertContains(response, reverse("validar_documento"))

    def test_lista_pacientes_ativos(self) -> None:
        _paciente(nome="Carlos Ativo", id_dental="A1")
        _paciente(nome="Ana Inativa", id_dental="A2", ativo=False)
        response = self.client.get(reverse("contratos"))
        self.assertContains(response, "Carlos Ativo")
        self.assertNotContains(response, "Ana Inativa")

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_busca_filtra_pacientes_por_nome(self, MockDental: MagicMock) -> None:
        MockDental.return_value.listar_pacientes.return_value = {"results": []}
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

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_busca_com_resultado_local_tambem_consulta_api(
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

        response = self.client.get(reverse("contratos"), {"q": "Helena"})

        mock_client.listar_pacientes.assert_called_once()
        self.assertContains(response, "Helena Local")
        self.assertContains(response, "Helena Dental")

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    def test_paginacao_nao_repete_consulta_api(self) -> None:
        _paciente(nome="Marcos Local", id_dental="A6")
        with patch("gestao_contratos.views.DentalClient") as MockDental:
            response = self.client.get(
                reverse("contratos"), {"q": "Marcos", "page": "2"}
            )
            MockDental.assert_not_called()
        self.assertContains(response, "Marcos Local")

    @override_settings(DENTAL_CLINIC_ID="clinic-001")
    @patch("gestao_contratos.views.DentalClient")
    def test_busca_consolida_multiplas_paginas_da_api(
        self, MockDental: MagicMock
    ) -> None:
        """Regressão do bug de paginação: uma busca com mais resultados do
        que o limite por página da API não deve mais ficar restrita à
        primeira página."""

        mock_client = MockDental.return_value
        mock_client.listar_pacientes.side_effect = [
            {
                "results": [
                    {
                        "id": i,
                        "name": f"Paciente API {i}",
                        "active": True,
                        "contacts_attributes": [],
                    }
                    for i in range(1, 61)
                ],
                "total_pages": 2,
            },
            {
                "results": [
                    {
                        "id": 61,
                        "name": "Paciente API 61",
                        "active": True,
                        "contacts_attributes": [],
                    }
                ],
                "total_pages": 2,
            },
        ]

        response = self.client.get(reverse("contratos"), {"q": "Paciente"})

        self.assertEqual(mock_client.listar_pacientes.call_count, 2)
        pacientes_api = response.context["pacientes_api"]
        self.assertEqual(len(pacientes_api), 61)
        nomes = {p["nome"] for p in pacientes_api}
        self.assertIn("Paciente API 1", nomes)
        self.assertIn("Paciente API 61", nomes)


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

    def test_get_nao_redireciona_mesmo_sem_confirmacao_previa(self) -> None:
        # A tela de confirmação foi unificada com a de geração: não há mais
        # um redirecionamento para uma tela separada — o próprio GET já
        # mostra o formulário (com o checklist indicando o que falta).
        pac = _paciente_completo(id_dental="205", dados_confirmados_em=None)

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/gerar_contrato.html")

    @patch("gestao_contratos.views.DentalClient")
    def test_get_retorna_200_sem_sincronizar_quando_completo(
        self, MockDental: MagicMock
    ) -> None:
        pac = _paciente_completo(id_dental="500")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
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

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

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
            reverse("contrato_gerar", args=[pac.pk]) + "?sincronizar=1",
            follow=True,
        )

        self.assertContains(response, "Dados atualizados")
        pac.refresh_from_db()
        self.assertIsNone(pac.dados_confirmados_em)
        # Convênio é local — sincronização não pode sobrescrevê-lo.
        self.assertEqual(pac.convenio, "Unimed")

    @patch("gestao_contratos.views.DentalClient")
    def test_sincronizacao_com_confirmacao_previa_sinaliza_banner(
        self, MockDental: MagicMock
    ) -> None:
        # Paciente já estava confirmado — a sincronização forçada invalida
        # essa confirmação, e o template precisa saber disso para destacar
        # o aviso (em vez do colaborador só descobrir ao tentar gerar).
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "document_attributes": {"cpf": "98765432100"},
            "addresses_attributes": [{"city": "Anápolis", "state": "GO"}],
            "contacts_attributes": [],
        }
        pac = _paciente_completo(id_dental="506")
        self.assertTrue(pac.dados_confirmados)

        response = self.client.get(
            reverse("contrato_gerar", args=[pac.pk]) + "?sincronizar=1"
        )

        self.assertTrue(response.context["sincronizacao_invalidou_confirmacao"])

    @patch("gestao_contratos.views.DentalClient")
    def test_sincronizacao_sem_confirmacao_previa_nao_sinaliza_banner(
        self, MockDental: MagicMock
    ) -> None:
        # Paciente incompleto nunca foi confirmado — a sincronização
        # automática aqui é a situação normal, não uma surpresa a avisar.
        MockDental.return_value.buscar_detalhes_paciente.return_value = {
            "document_attributes": {"cpf": "98765432100"},
            "addresses_attributes": [{"city": "Goiânia", "state": "GO"}],
            "contacts_attributes": [],
        }
        pac = _paciente(id_dental="507")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertFalse(response.context["sincronizacao_invalidou_confirmacao"])

    @patch("gestao_contratos.views.DentalClient")
    def test_erro_dental_na_sync_exibe_aviso_sem_quebrar(
        self, MockDental: MagicMock
    ) -> None:
        MockDental.return_value.buscar_detalhes_paciente.side_effect = DentalAPIError(
            "timeout"
        )
        # Paciente incompleto (sem CPF e sem cidade) dispara sync automático
        pac = _paciente(id_dental="503")

        response = self.client.get(reverse("contrato_gerar", args=[pac.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "timeout")


# ---------------------------------------------------------------------------
# Testes de Views — alias de compatibilidade da antiga tela de confirmação
# ---------------------------------------------------------------------------


class ConfirmarDadosAliasTests(TestCase):
    """A tela de confirmação foi unificada com a de geração do contrato —
    esta URL só existe para não quebrar links/favoritos antigos."""

    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_redireciona_para_gerar_contrato(self) -> None:
        pac = _paciente_completo(id_dental="509")

        response = self.client.get(reverse("contrato_confirmar_dados", args=[pac.pk]))

        self.assertRedirects(
            response,
            reverse("contrato_gerar", args=[pac.pk]),
            fetch_redirect_response=False,
        )


# ---------------------------------------------------------------------------
# Testes de Views — gerar contrato (POST)
# ---------------------------------------------------------------------------


class GerarContratoPostTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def _dados_paciente(self, paciente: Paciente, **kwargs) -> dict:
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

    def _dados_post(self, paciente: Paciente, **kwargs) -> dict:
        base = self._dados_paciente(paciente)
        base.update(
            {
                "tipo": "modelo_1",
                "observacoes_clinicas": "Sem intercorrências.",
                "profissional_nome": "Dr. Teste",
                "local_assinatura": "Goiânia - GO",
            }
        )
        base.update(kwargs)
        return base

    def test_post_com_pendencias_reexibe_formulario_sem_gerar(self) -> None:
        # Paciente sem CPF/cidade — o checklist deve barrar a geração, mas
        # os dados enviados ainda são salvos e marcados como confirmados
        # (a confirmação e a geração são a mesma etapa agora, porém a
        # geração em si fica bloqueada até os campos serem completados).
        pac = _paciente(id_dental="300")

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "campos obrigatórios pendentes")
        self.assertEqual(ContratoGerado.objects.count(), 0)
        pac.refresh_from_db()
        self.assertIsNotNone(pac.dados_confirmados_em)

    def test_post_sem_nome_reexibe_formulario_sem_confirmar(self) -> None:
        pac = _paciente_completo(id_dental="505", dados_confirmados_em=None)

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac, nome=""),
        )

        self.assertEqual(response.status_code, 200)
        pac.refresh_from_db()
        self.assertIsNone(pac.dados_confirmados_em)

    @patch("gestao_contratos.views.gerar_e_salvar_contrato")
    def test_post_valido_confirma_gera_contrato_e_redireciona(
        self, mock_gerar: MagicMock
    ) -> None:
        pac = _paciente_completo(id_dental="301", dados_confirmados_em=None)
        contrato = ContratoGerado.objects.create(
            paciente=pac, tipo="modelo_1", gerado_por=self.usuario
        )
        mock_gerar.return_value = contrato

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac, convenio="Amil", celular="(62) 98888-7777"),
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

        pac.refresh_from_db()
        self.assertEqual(pac.convenio, "Amil")
        self.assertEqual(pac.celular, "(62) 98888-7777")
        self.assertIsNotNone(pac.dados_confirmados_em)
        self.assertEqual(pac.dados_confirmados_por, self.usuario)

    @patch("gestao_contratos.views.gerar_e_salvar_contrato")
    def test_post_com_email_diferente_atualiza_paciente(
        self, mock_gerar: MagicMock
    ) -> None:
        pac = _paciente_completo(id_dental="303")
        contrato = ContratoGerado.objects.create(
            paciente=pac, tipo="modelo_1", gerado_por=self.usuario
        )
        mock_gerar.return_value = contrato

        self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac, email="novo@example.com"),
        )

        pac.refresh_from_db()
        self.assertEqual(pac.email, "novo@example.com")

    @patch("gestao_contratos.views.gerar_e_salvar_contrato")
    def test_post_arquivo_modelo_ausente_redireciona_com_erro(
        self, mock_gerar: MagicMock
    ) -> None:
        pac = _paciente_completo(id_dental="304")
        mock_gerar.side_effect = FileNotFoundError("Modelo de contrato não encontrado")

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac),
            follow=True,
        )

        self.assertContains(response, "Modelo de contrato não encontrado")
        self.assertEqual(ContratoGerado.objects.count(), 0)

    def test_post_com_tipo_invalido_redireciona_com_erro(self) -> None:
        pac = _paciente_completo(id_dental="302")

        response = self.client.post(
            reverse("contrato_gerar", args=[pac.pk]),
            data=self._dados_post(pac, tipo="tipo_invalido"),
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


def _confirmar_identidade_sessao(
    sessao: SessaoAssinatura, como: str = "paciente"
) -> None:
    """Marca a identidade como já confirmada, sem passar pela tela.

    Usado por testes cujo foco é o comportamento pós-verificação (ex.:
    assinatura em si) — o fluxo de verificação de identidade tem sua
    própria suíte dedicada (VerificarIdentidadeTests / VerificarIdentidadeMenorTests).
    """
    sessao.identidade_confirmada_em = timezone.now()
    sessao.identidade_confirmada_como = como
    sessao.save(
        update_fields=[
            "identidade_confirmada_em",
            "identidade_confirmada_como",
            "atualizado_em",
        ]
    )


class AssinaturaBaseTests(TestCase):
    """Base: contrato real (com PDF) em MEDIA_ROOT temporário.

    ``enviar_dental_task.delay``, ``enviar_whatsapp_task.delay`` e
    ``solicitar_carimbo_tempo_task.delay`` são mockadas aqui porque, em
    CELERY_TASK_ALWAYS_EAGER (ativo durante os testes), qualquer chamada
    real executaria a tarefa de forma síncrona — incluindo uma tentativa
    de rede à API real do Dental Office, já que este projeto tem um .env
    com credenciais válidas (e, no dia em que CARIMBO_TEMPO_TSA_URL for
    configurada em produção, uma tentativa de rede real à TSA). O
    comportamento real de cada tarefa é coberto isoladamente em
    EnviarDentalTaskTests, EnviarWhatsappTaskTests e
    SolicitarCarimboTempoTaskTests, que não herdam desta base.
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

        patcher_wa = patch("gestao_contratos.tasks.enviar_whatsapp_task.delay")
        self.mock_enviar_whatsapp_delay = patcher_wa.start()
        self.addCleanup(patcher_wa.stop)

        patcher_carimbo = patch(
            "gestao_contratos.tasks.solicitar_carimbo_tempo_task.delay"
        )
        self.mock_solicitar_carimbo_delay = patcher_carimbo.start()
        self.addCleanup(patcher_carimbo.stop)


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

    def test_criar_sessao_sem_confirmacao_presencial_nao_registra_evento(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        self.assertIsNone(sessao.identidade_presencial_confirmada_em)
        self.assertFalse(sessao.identidade_presencial_confirmada)
        self.assertFalse(
            EventoContrato.objects.filter(
                sessao=sessao, tipo="identidade_presencial_confirmada"
            ).exists()
        )

    def test_criar_sessao_com_confirmacao_presencial_registra_evento(self) -> None:
        agora = timezone.now()
        sessao = criar_sessao(
            self.contrato,
            criado_por=self.usuario,
            identidade_presencial_confirmada_em=agora,
        )

        self.assertEqual(sessao.identidade_presencial_confirmada_em, agora)
        self.assertTrue(sessao.identidade_presencial_confirmada)
        evento = EventoContrato.objects.get(
            sessao=sessao, tipo="identidade_presencial_confirmada"
        )
        self.assertEqual(evento.payload.get("confirmada_por"), self.usuario.username)


class EventosRecentesTests(AssinaturaBaseTests):
    """Eventos "iniciado" de tarefa assíncrona (com par concluído/erro) não
    devem aparecer na linha do tempo — são ruído técnico redundante assim
    que o desfecho chega. Eventos sem par de conclusão (ex.: sessão criada)
    continuam aparecendo, pois são o único registro daquele marco."""

    def test_oculta_eventos_de_inicio_com_par_de_conclusao(self) -> None:
        for tipo in (
            "envio_dental_iniciado",
            "whatsapp_iniciado",
            "carimbo_tempo_iniciado",
        ):
            EventoContrato.objects.create(contrato=self.contrato, tipo=tipo)
        EventoContrato.objects.create(
            contrato=self.contrato, tipo="envio_dental_concluido"
        )

        tipos = [e.tipo for e in eventos_recentes(self.contrato)]

        self.assertNotIn("envio_dental_iniciado", tipos)
        self.assertNotIn("whatsapp_iniciado", tipos)
        self.assertNotIn("carimbo_tempo_iniciado", tipos)
        self.assertIn("envio_dental_concluido", tipos)

    def test_mantem_eventos_sem_par_de_conclusao(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)

        tipos = [e.tipo for e in eventos_recentes(self.contrato)]

        self.assertIn("sessao_criada", tipos)

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

    @override_settings(
        ZAPI_INSTANCE_ID="instancia-teste",
        ZAPI_TOKEN="token-teste",
    )
    def test_assinatura_agenda_envio_whatsapp_quando_configurado_e_com_celular(
        self,
    ) -> None:
        self.pac.celular = "62999998888"
        self.pac.save(update_fields=["celular"])
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_whatsapp_delay.assert_called_once_with(self.contrato.pk)

    @override_settings(ZAPI_INSTANCE_ID="", ZAPI_TOKEN="")
    def test_assinatura_nao_agenda_whatsapp_sem_zapi_configurado(self) -> None:
        """Sem credenciais da Z-API, o envio automático fica desativado —
        mesmo com celular cadastrado. Zera as settings explicitamente para
        não depender do que estiver no .env do desenvolvedor."""
        self.pac.celular = "62999998888"
        self.pac.save(update_fields=["celular"])
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_whatsapp_delay.assert_not_called()

    @override_settings(
        ZAPI_INSTANCE_ID="instancia-teste",
        ZAPI_TOKEN="token-teste",
    )
    def test_assinatura_nao_agenda_whatsapp_sem_celular(self) -> None:
        """Configurado, mas sem celular do paciente, não há para quem enviar."""
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_whatsapp_delay.assert_not_called()

    @override_settings(
        ZAPI_INSTANCE_ID="instancia-teste",
        ZAPI_TOKEN="token-teste",
    )
    def test_falha_ao_enfileirar_whatsapp_nao_quebra_a_assinatura(self) -> None:
        self.pac.celular = "62999998888"
        self.pac.save(update_fields=["celular"])
        self.mock_enviar_whatsapp_delay.side_effect = RuntimeError(
            "Retry limit exceeded while trying to reconnect to the Celery "
            "result store backend."
        )
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        contrato = processar_assinatura(
            sessao, _assinatura_data_url(), ip=None, user_agent=""
        )

        self.assertEqual(contrato.status, "assinado")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=contrato, tipo="whatsapp_erro"
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
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")

    def test_get_apos_identidade_confirmada_exibe_assinar(self) -> None:
        self.client.logout()
        _confirmar_identidade_sessao(self.sessao)
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

    def test_pdf_publico_acessivel_apos_confirmar_identidade(self) -> None:
        self.client.logout()
        _confirmar_identidade_sessao(self.sessao)
        response = self.client.get(reverse("assinatura_publica_pdf", args=[self.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_publico_negado_sem_confirmar_identidade(self) -> None:
        """C-01: só ter o link/QR Code não basta para baixar o termo.

        O PDF traz CPF, RG, endereço e dados de saúde — entregá-lo antes da
        verificação anulava, na prática, a tela de identidade.
        """

        self.client.logout()
        response = self.client.get(reverse("assinatura_publica_pdf", args=[self.token]))
        self.assertEqual(response.status_code, 404)

    def test_post_assina_e_exibe_confirmacao(self) -> None:
        self.client.logout()
        _confirmar_identidade_sessao(self.sessao)
        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "assinado")

    def test_acesso_apos_assinatura_retorna_410(self) -> None:
        self.client.logout()
        _confirmar_identidade_sessao(self.sessao)
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
        _confirmar_identidade_sessao(self.sessao)

        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "assinado")

    def test_post_imagem_invalida_reexibe_pagina_com_erro(self) -> None:
        self.client.logout()
        _confirmar_identidade_sessao(self.sessao)
        response = self.client.post(self.url, data={"assinatura": "lixo"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")
        self.contrato.refresh_from_db()
        self.assertNotEqual(self.contrato.status, "assinado")


class VerificarIdentidadeTests(AssinaturaBaseTests):
    """Confirmação da data de nascimento antes de liberar o canvas.

    ``_paciente_completo`` cadastra data_nascimento=1990-05-15 — usada
    como a data "correta" nestes testes.
    """

    def setUp(self) -> None:
        super().setUp()
        self.sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        self.token = gerar_token(self.sessao)
        self.url = reverse("assinatura_publica", args=[self.token])
        self.client.logout()

    def test_get_exibe_formulario_sem_expor_contrato(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.assertNotContains(response, 'id="pad"')

    def test_data_correta_confirma_e_libera_assinatura(self) -> None:
        response = self.client.post(self.url, data={"nascimento": "1990-05-15"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")
        self.assertContains(response, 'id="pad"')

        self.sessao.refresh_from_db()
        self.assertIsNotNone(self.sessao.identidade_confirmada_em)
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=self.sessao, tipo="identidade_confirmada"
            ).exists()
        )

    def test_data_incorreta_reexibe_formulario_com_erro(self) -> None:
        response = self.client.post(self.url, data={"nascimento": "2000-01-01"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.assertContains(response, "incorreta")

        self.sessao.refresh_from_db()
        self.assertIsNone(self.sessao.identidade_confirmada_em)
        self.assertEqual(self.sessao.tentativas_identidade, 1)

    def test_data_em_formato_invalido_e_tratada_como_incorreta(self) -> None:
        response = self.client.post(self.url, data={"nascimento": "não é uma data"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.tentativas_identidade, 1)

    def test_bloqueia_apos_exceder_tentativas(self) -> None:
        for _ in range(LIMITE_TENTATIVAS_IDENTIDADE - 1):
            response = self.client.post(self.url, data={"nascimento": "2000-01-01"})
            self.assertEqual(response.status_code, 200)

        response = self.client.post(self.url, data={"nascimento": "2000-01-01"})

        self.assertEqual(response.status_code, 410)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_invalida.html")
        self.assertContains(response, "bloqueada", status_code=410)

        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.status, "cancelada")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "gerado")
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=self.sessao, tipo="identidade_bloqueada"
            ).exists()
        )

    def test_get_apos_bloqueio_retorna_410(self) -> None:
        for _ in range(LIMITE_TENTATIVAS_IDENTIDADE):
            self.client.post(self.url, data={"nascimento": "2000-01-01"})

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 410)

    def test_assinatura_direta_sem_confirmar_identidade_nao_assina(self) -> None:
        """Defesa em profundidade: mesmo pulando a tela e enviando o campo
        'assinatura' diretamente, sem confirmar a identidade, o contrato
        não é assinado."""
        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.contrato.refresh_from_db()
        self.assertNotEqual(self.contrato.status, "assinado")
        self.sessao.refresh_from_db()
        self.assertIsNone(self.sessao.identidade_confirmada_em)

    def test_confirmar_identidade_sem_data_nascimento_cadastrada(self) -> None:
        """Unidade: sem data de nascimento cadastrada, confirmar_identidade
        nunca deve confirmar (evita comparar None == None e liberar a
        assinatura sem checagem real)."""
        self.pac.data_nascimento = None
        self.pac.save(update_fields=["data_nascimento"])

        self.assertFalse(confirmar_identidade(self.sessao, ""))
        self.sessao.refresh_from_db()
        self.assertIsNone(self.sessao.identidade_confirmada_em)


class VerificarIdentidadeMenorTests(AssinaturaBaseTests):
    """Paciente menor de idade — quem assina é o responsável legal,
    confirmando o CPF cadastrado em vez da data de nascimento."""

    def setUp(self) -> None:
        super().setUp()
        hoje = date.today()
        nascimento_menor = date(hoje.year - 10, hoje.month, hoje.day)
        self.pac_menor = _paciente_completo(
            id_dental="700",
            data_nascimento=nascimento_menor,
            nome_responsavel="Maria Responsável",
            cpf_responsavel="999.888.777-66",
        )
        self.contrato_menor = gerar_e_salvar_contrato(
            paciente=self.pac_menor, tipo="modelo_1", gerado_por=self.usuario
        )
        self.sessao = criar_sessao(self.contrato_menor, criado_por=self.usuario)
        self.token = gerar_token(self.sessao)
        self.url = reverse("assinatura_publica", args=[self.token])
        self.client.logout()

    def test_get_exibe_formulario_de_cpf_do_responsavel(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.assertContains(response, "responsável legal")
        self.assertNotContains(response, 'name="nascimento"')
        self.assertContains(response, 'name="cpf_responsavel"')

    def test_cpf_correto_confirma_como_responsavel_legal(self) -> None:
        response = self.client.post(self.url, data={"cpf_responsavel": "99988877766"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")
        self.assertContains(response, "responsável legal")

        self.sessao.refresh_from_db()
        self.assertIsNotNone(self.sessao.identidade_confirmada_em)
        self.assertEqual(self.sessao.identidade_confirmada_como, "responsavel_legal")
        self.assertTrue(self.sessao.assinado_por_responsavel)
        evento = EventoContrato.objects.get(
            sessao=self.sessao, tipo="identidade_confirmada"
        )
        self.assertEqual(evento.payload.get("confirmado_como"), "responsavel_legal")

    def test_cpf_com_pontuacao_tambem_confere(self) -> None:
        response = self.client.post(
            self.url, data={"cpf_responsavel": "999.888.777-66"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinar.html")

    def test_cpf_incorreto_reexibe_formulario_do_responsavel(self) -> None:
        response = self.client.post(self.url, data={"cpf_responsavel": "00000000000"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.assertContains(response, "CPF do responsável legal incorreto")

        self.sessao.refresh_from_db()
        self.assertIsNone(self.sessao.identidade_confirmada_em)
        self.assertEqual(self.sessao.tentativas_identidade, 1)

    def test_data_de_nascimento_nao_confirma_identidade_do_menor(self) -> None:
        """O campo relevante para um menor é o CPF do responsável — enviar
        a própria data de nascimento (paciente errado) não deve confirmar."""
        response = self.client.post(
            self.url,
            data={"nascimento": self.pac_menor.data_nascimento.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/verificar_identidade.html")
        self.sessao.refresh_from_db()
        self.assertIsNone(self.sessao.identidade_confirmada_em)

    def test_bloqueia_apos_exceder_tentativas(self) -> None:
        for _ in range(LIMITE_TENTATIVAS_IDENTIDADE - 1):
            response = self.client.post(
                self.url, data={"cpf_responsavel": "00000000000"}
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(self.url, data={"cpf_responsavel": "00000000000"})

        self.assertEqual(response.status_code, 410)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_invalida.html")

        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.status, "cancelada")
        self.contrato_menor.refresh_from_db()
        self.assertEqual(self.contrato_menor.status, "gerado")

    def test_assinatura_concluida_menciona_responsavel_legal(self) -> None:
        self.client.post(self.url, data={"cpf_responsavel": "99988877766"})

        response = self.client.post(
            self.url, data={"assinatura": _assinatura_data_url()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.assertContains(response, "responsável legal")
        self.contrato_menor.refresh_from_db()
        self.assertEqual(self.contrato_menor.status, "assinado")

    def test_processar_assinatura_registra_evento_com_papel_do_responsavel(
        self,
    ) -> None:
        _confirmar_identidade_sessao(self.sessao, como="responsavel_legal")

        processar_assinatura(
            self.sessao, _assinatura_data_url(), ip="203.0.113.10", user_agent="X"
        )

        evento = EventoContrato.objects.get(
            sessao=self.sessao, tipo="assinatura_concluida"
        )
        self.assertEqual(evento.payload.get("assinado_como"), "responsavel_legal")


class AssinaturaStaffViewTests(AssinaturaBaseTests):
    def test_iniciar_assinatura_cria_sessao(self) -> None:
        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            data={"identidade_presencial_confirmada": "on"},
        )

        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )
        sessao = sessao_ativa(self.contrato)
        self.assertIsNotNone(sessao)
        self.assertIsNotNone(sessao.identidade_presencial_confirmada_em)
        self.assertTrue(
            EventoContrato.objects.filter(
                sessao=sessao, tipo="identidade_presencial_confirmada"
            ).exists()
        )

    def test_iniciar_assinatura_sem_confirmacao_presencial_nao_cria_sessao(
        self,
    ) -> None:
        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            follow=True,
        )

        self.assertContains(response, "Confirme que verificou a identidade")
        self.assertIsNone(sessao_ativa(self.contrato))

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


class EnviarContratoEmailTests(AssinaturaBaseTests):
    """Regressão: o e-mail também não priorizava o PDF assinado."""

    def test_prefere_pdf_assinado_quando_disponivel(self) -> None:
        from django.core.files.base import ContentFile
        from gestao_contratos.services.envio import enviar_contrato_email

        self.contrato.arquivo_pdf.open("rb")
        conteudo_original = self.contrato.arquivo_pdf.read()
        self.contrato.arquivo_pdf.close()
        conteudo_assinado = conteudo_original + b"-ASSINADO"
        self.contrato.arquivo_pdf_assinado.save(
            "assinado.pdf", ContentFile(conteudo_assinado), save=True
        )

        ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        _, conteudo_enviado, _ = mail.outbox[0].attachments[0]
        self.assertEqual(conteudo_enviado, conteudo_assinado)

    def test_usa_pdf_original_quando_ainda_nao_assinado(self) -> None:
        from gestao_contratos.services.envio import enviar_contrato_email

        self.contrato.arquivo_pdf.open("rb")
        conteudo_original = self.contrato.arquivo_pdf.read()
        self.contrato.arquivo_pdf.close()

        ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertTrue(ok)
        _, conteudo_enviado, _ = mail.outbox[0].attachments[0]
        self.assertEqual(conteudo_enviado, conteudo_original)


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


# ---------------------------------------------------------------------------
# Testes do envio automático por WhatsApp — Z-API (Fase 7)
# ---------------------------------------------------------------------------


class NormalizarCelularTests(TestCase):
    def test_remove_nao_digitos(self) -> None:
        self.assertEqual(normalizar_celular("(62) 9 9999-8888"), "5562999998888")

    def test_adiciona_55_se_ausente(self) -> None:
        self.assertEqual(normalizar_celular("62999998888"), "5562999998888")

    def test_mantem_55_se_ja_presente(self) -> None:
        self.assertEqual(normalizar_celular("5562999998888"), "5562999998888")

    def test_vazio_para_string_vazia(self) -> None:
        self.assertEqual(normalizar_celular(""), "")

    def test_vazio_para_string_sem_digitos(self) -> None:
        self.assertEqual(normalizar_celular("abc"), "")


class ValidarDestinatarioTests(TestCase):
    def test_numero_valido_e_retornado_sem_alteracao(self) -> None:
        self.assertEqual(validar_destinatario("5562999998888"), "5562999998888")

    def test_numero_vazio_levanta_invalid_recipient(self) -> None:
        with self.assertRaises(InvalidRecipientError):
            validar_destinatario("")

    def test_numero_curto_demais_levanta_invalid_recipient(self) -> None:
        with self.assertRaises(InvalidRecipientError):
            validar_destinatario("123")

    def test_numero_com_letras_levanta_invalid_recipient(self) -> None:
        with self.assertRaises(InvalidRecipientError):
            validar_destinatario("55629999-8888")


class CarregarConfigZApiTests(TestCase):
    @override_settings(ZAPI_INSTANCE_ID="", ZAPI_TOKEN="")
    def test_sem_variaveis_retorna_none(self) -> None:
        self.assertIsNone(carregar_config_zapi())

    @override_settings(
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="tok",
        ZAPI_CLIENT_TOKEN="",
        ZAPI_BASE_URL="https://api.z-api.io",
        ZAPI_TIMEOUT=30,
    )
    def test_com_variaveis_obrigatorias_usa_padroes_para_opcionais(self) -> None:
        config = carregar_config_zapi()
        self.assertIsNotNone(config)
        self.assertEqual(config.instance_id, "inst")
        self.assertEqual(config.token, "tok")
        self.assertEqual(config.client_token, "")
        self.assertEqual(config.base_url, "https://api.z-api.io")
        self.assertEqual(config.timeout, 30)

    @override_settings(
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="tok",
        ZAPI_CLIENT_TOKEN="client-tok",
        ZAPI_BASE_URL="https://api.z-api.io/",
        ZAPI_TIMEOUT=45,
    )
    def test_respeita_variaveis_opcionais_quando_definidas(self) -> None:
        config = carregar_config_zapi()
        self.assertEqual(config.client_token, "client-tok")
        self.assertEqual(config.base_url, "https://api.z-api.io")
        self.assertEqual(config.timeout, 45)

    @override_settings(ZAPI_INSTANCE_ID="inst", ZAPI_TOKEN="")
    def test_apenas_instance_id_sem_token_retorna_none(self) -> None:
        self.assertIsNone(carregar_config_zapi())


def _fake_http_response(corpo: dict, status: int = 200) -> MagicMock:
    """Simula o context manager retornado por urlopen()."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(corpo).encode("utf-8")
    cm.__enter__.return_value.status = status
    return cm


def _fake_http_error(status: int, corpo: str):
    from urllib.error import HTTPError

    fp = io.BytesIO(corpo.encode("utf-8"))
    return HTTPError(
        url="https://api.z-api.io/teste",
        code=status,
        msg="erro",
        hdrs=None,
        fp=fp,
    )


class ZApiProviderTests(TestCase):
    def _config(self, **kwargs):
        valores = {"ZAPI_INSTANCE_ID": "inst", "ZAPI_TOKEN": "tok", **kwargs}
        with override_settings(**valores):
            return carregar_config_zapi()

    def test_sem_config_levanta_erro_ao_instanciar(self) -> None:
        with override_settings(ZAPI_INSTANCE_ID="", ZAPI_TOKEN=""):
            with self.assertRaises(MessagingError):
                ZApiProvider()

    @patch("mensageria.zapi.urlopen")
    def test_envia_texto_com_sucesso(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"messageId": "zaap-1"})

        provider = ZApiProvider(self._config())
        resultado = provider.enviar_texto("5562999998888", "Olá!")

        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.message_id, "zaap-1")
        chamada = mock_urlopen.call_args[0][0]
        self.assertTrue(chamada.full_url.endswith("/send-text"))
        payload = json.loads(chamada.data)
        self.assertEqual(payload["phone"], "5562999998888")
        self.assertEqual(payload["message"], "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_envia_documento_com_sucesso(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"messageId": "zaap-2"})

        provider = ZApiProvider(self._config())
        resultado = provider.enviar_documento(
            destinatario="5562999998888",
            arquivo_bytes=b"%PDF-fake",
            nome_arquivo="contrato.pdf",
            legenda="Segue o contrato",
        )

        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.message_id, "zaap-2")
        chamada = mock_urlopen.call_args[0][0]
        self.assertTrue(chamada.full_url.endswith("/send-document/pdf"))
        payload = json.loads(chamada.data)
        self.assertEqual(payload["fileName"], "contrato.pdf")
        self.assertEqual(payload["caption"], "Segue o contrato")
        self.assertTrue(payload["document"].startswith("data:application/pdf;base64,"))

    @patch("mensageria.zapi.urlopen")
    def test_envia_imagem_com_sucesso(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"messageId": "zaap-3"})

        provider = ZApiProvider(self._config())
        resultado = provider.enviar_imagem(
            destinatario="5562999998888", arquivo_bytes=b"\x89PNG-fake", legenda="Foto"
        )

        self.assertTrue(resultado.sucesso)
        chamada = mock_urlopen.call_args[0][0]
        self.assertTrue(chamada.full_url.endswith("/send-image"))
        payload = json.loads(chamada.data)
        self.assertTrue(payload["image"].startswith("data:image/png;base64,"))

    @patch("mensageria.zapi.urlopen")
    def test_enviar_arquivo_escolhe_imagem_por_content_type(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _fake_http_response({"messageId": "zaap-4"})

        provider = ZApiProvider(self._config())
        provider.enviar_arquivo(
            "5562999998888", b"dados", "foto.jpg", "image/jpeg", legenda="Foto"
        )

        chamada = mock_urlopen.call_args[0][0]
        self.assertTrue(chamada.full_url.endswith("/send-image"))

    @patch("mensageria.zapi.urlopen")
    def test_enviar_arquivo_escolhe_documento_por_content_type(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _fake_http_response({"messageId": "zaap-5"})

        provider = ZApiProvider(self._config())
        provider.enviar_arquivo(
            "5562999998888",
            b"dados",
            "planilha.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        chamada = mock_urlopen.call_args[0][0]
        self.assertTrue(chamada.full_url.endswith("/send-document/xlsx"))

    @patch("mensageria.zapi.urlopen")
    def test_destinatario_invalido_nao_chega_a_chamar_a_api(
        self, mock_urlopen: MagicMock
    ) -> None:
        provider = ZApiProvider(self._config())
        with self.assertRaises(InvalidRecipientError):
            provider.enviar_texto("", "Olá!")
        mock_urlopen.assert_not_called()

    @patch("mensageria.zapi.urlopen")
    def test_resposta_com_error_vira_message_rejected(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _fake_http_response(
            {"error": "number-not-whatsapp"}
        )

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessageRejectedError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_resposta_sem_id_levanta_erro(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"algo": "inesperado"})

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessagingError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_http_401_vira_erro_de_autenticacao(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = _fake_http_error(401, '{"error": "token invalido"}')

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessagingAuthenticationError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_http_404_vira_instancia_desconectada(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = _fake_http_error(404, '{"error": "not found"}')

        provider = ZApiProvider(self._config())
        with self.assertRaises(InstanceDisconnectedError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_http_429_vira_limite_excedido(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = _fake_http_error(429, '{"error": "rate limit"}')

        provider = ZApiProvider(self._config())
        with self.assertRaises(RateLimitExceededError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_http_500_vira_provedor_indisponivel(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = _fake_http_error(500, '{"error": "internal"}')

        provider = ZApiProvider(self._config())
        with self.assertRaises(ProviderUnavailableError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_falha_de_conexao_vira_provedor_indisponivel(
        self, mock_urlopen: MagicMock
    ) -> None:
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("conexão recusada")

        provider = ZApiProvider(self._config())
        with self.assertRaises(ProviderUnavailableError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_timeout_vira_messaging_timeout_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = TimeoutError("tempo esgotado")

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessagingTimeoutError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_corpo_vazio_retorna_dict_vazio_e_falta_de_id_levanta_erro(
        self, mock_urlopen: MagicMock
    ) -> None:
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = b""
        cm.__enter__.return_value.status = 200
        mock_urlopen.return_value = cm

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessagingError):
            provider.enviar_texto("5562999998888", "Olá!")

    @patch("mensageria.zapi.urlopen")
    def test_resposta_nao_json_levanta_erro(self, mock_urlopen: MagicMock) -> None:
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = b"<html>erro</html>"
        cm.__enter__.return_value.status = 200
        mock_urlopen.return_value = cm

        provider = ZApiProvider(self._config())
        with self.assertRaises(MessagingError):
            provider.enviar_texto("5562999998888", "Olá!")


class ZApiProviderDisponibilidadeTests(TestCase):
    def _config(self, **kwargs):
        valores = {"ZAPI_INSTANCE_ID": "inst", "ZAPI_TOKEN": "tok", **kwargs}
        with override_settings(**valores):
            return carregar_config_zapi()

    @patch("mensageria.zapi.urlopen")
    def test_instancia_conectada(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"connected": True})

        resultado = ZApiProvider(self._config()).verificar_disponibilidade()

        self.assertTrue(resultado.disponivel)

    @patch("mensageria.zapi.urlopen")
    def test_instancia_desconectada(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _fake_http_response({"connected": False})

        resultado = ZApiProvider(self._config()).verificar_disponibilidade()

        self.assertFalse(resultado.disponivel)
        self.assertIn("QR Code", resultado.detalhe)

    @patch("mensageria.zapi.urlopen")
    def test_erro_de_rede_reporta_indisponivel_sem_levantar_excecao(
        self, mock_urlopen: MagicMock
    ) -> None:
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("indisponível")

        resultado = ZApiProvider(self._config()).verificar_disponibilidade()

        self.assertFalse(resultado.disponivel)
        self.assertTrue(resultado.detalhe)


class MessagingServiceRetryTests(TestCase):
    """Testa o retry com backoff do MessagingService isoladamente, sem HTTP —
    a comunicação em si já é coberta por ZApiProviderTests."""

    def setUp(self) -> None:
        from mensageria import MessagingService

        self.provider = MagicMock()
        self.service = MessagingService(
            self.provider, tentativas=3, backoff_base_segundos=0
        )

    def test_sucesso_de_primeira_nao_tenta_novamente(self) -> None:
        self.provider.enviar_texto.return_value = MessagingResult.ok("id-1")

        resultado = self.service.enviar_texto("5562999998888", "Olá!")

        self.assertTrue(resultado.sucesso)
        self.assertEqual(self.provider.enviar_texto.call_count, 1)

    def test_erro_transitorio_e_tentado_novamente_ate_suceder(self) -> None:
        self.provider.enviar_texto.side_effect = [
            ProviderUnavailableError("instável"),
            MessagingResult.ok("id-2"),
        ]

        resultado = self.service.enviar_texto("5562999998888", "Olá!")

        self.assertTrue(resultado.sucesso)
        self.assertEqual(self.provider.enviar_texto.call_count, 2)

    def test_erro_transitorio_persistente_esgota_tentativas_e_retorna_falha(
        self,
    ) -> None:
        self.provider.enviar_texto.side_effect = ProviderUnavailableError("fora do ar")

        resultado = self.service.enviar_texto("5562999998888", "Olá!")

        self.assertFalse(resultado.sucesso)
        self.assertEqual(self.provider.enviar_texto.call_count, 3)

    def test_erro_nao_transitorio_nao_e_tentado_novamente(self) -> None:
        self.provider.enviar_texto.side_effect = InvalidRecipientError("inválido")

        resultado = self.service.enviar_texto("5562999998888", "Olá!")

        self.assertFalse(resultado.sucesso)
        self.assertEqual(self.provider.enviar_texto.call_count, 1)

    def test_verificar_disponibilidade_nunca_levanta_excecao(self) -> None:
        self.provider.verificar_disponibilidade.side_effect = MessagingError("falha")

        resultado = self.service.verificar_disponibilidade()

        self.assertFalse(resultado.disponivel)


class EnviarWhatsappContratoTests(AssinaturaBaseTests):
    """Testa enviar_whatsapp_contrato() mockando o serviço de mensageria
    inteiro — a comunicação HTTP com a Z-API já é coberta por ZApiProviderTests."""

    def setUp(self) -> None:
        super().setUp()
        self.pac.celular = "62999998888"
        self.pac.save(update_fields=["celular"])

    @patch("gestao_contratos.services.whatsapp.get_messaging_service")
    def test_sucesso_atualiza_status_e_registra_evento(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_documento.return_value = (
            MessagingResult.ok("zaap-123")
        )

        ok, erro = enviar_whatsapp_contrato(self.contrato)

        self.assertTrue(ok)
        self.assertEqual(erro, "")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "enviado_whatsapp")
        evento = EventoContrato.objects.filter(
            contrato=self.contrato, tipo="whatsapp_concluido"
        ).first()
        self.assertIsNotNone(evento)
        self.assertEqual(evento.payload.get("message_id"), "zaap-123")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="whatsapp_iniciado"
            ).exists()
        )

    @patch("gestao_contratos.services.whatsapp.get_messaging_service")
    def test_erro_da_api_registra_evento_de_erro(
        self, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_documento.return_value = (
            MessagingResult.falha("falha simulada")
        )

        ok, erro = enviar_whatsapp_contrato(self.contrato)

        self.assertFalse(ok)
        self.assertIn("falha simulada", erro)
        evento = EventoContrato.objects.filter(
            contrato=self.contrato, tipo="whatsapp_erro"
        ).first()
        self.assertIsNotNone(evento)
        self.assertIn("falha simulada", evento.payload.get("erro", ""))

    @patch("gestao_contratos.services.whatsapp.get_messaging_service")
    def test_sem_celular_nao_chama_a_api(self, mock_get_service: MagicMock) -> None:
        self.pac.celular = ""
        self.pac.save(update_fields=["celular"])

        ok, erro = enviar_whatsapp_contrato(self.contrato)

        self.assertFalse(ok)
        mock_get_service.assert_not_called()
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="whatsapp_erro"
            ).exists()
        )

    @patch("gestao_contratos.services.whatsapp.get_messaging_service")
    def test_prefere_pdf_assinado_quando_disponivel(
        self, mock_get_service: MagicMock
    ) -> None:
        from django.core.files.base import ContentFile

        self.contrato.arquivo_pdf.open("rb")
        conteudo_original = self.contrato.arquivo_pdf.read()
        self.contrato.arquivo_pdf.close()
        conteudo_assinado = conteudo_original + b"-ASSINADO"
        self.contrato.arquivo_pdf_assinado.save(
            "assinado.pdf", ContentFile(conteudo_assinado), save=True
        )
        mock_get_service.return_value.enviar_documento.return_value = (
            MessagingResult.ok("zaap-999")
        )

        ok, erro = enviar_whatsapp_contrato(self.contrato)

        self.assertTrue(ok)
        kwargs = mock_get_service.return_value.enviar_documento.call_args.kwargs
        self.assertEqual(kwargs["arquivo_bytes"], conteudo_assinado)


class EnviarWhatsappTaskTests(TestCase):
    """Testa enviar_whatsapp_task diretamente — sem herdar de
    AssinaturaBaseTests, que mocka justamente ``.delay()`` desta tarefa."""

    def setUp(self) -> None:
        self.usuario = _usuario()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="710", celular="62999998888")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )

    @patch("gestao_contratos.services.whatsapp.enviar_whatsapp_contrato")
    def test_sucesso_chama_uma_unica_vez(self, mock_enviar: MagicMock) -> None:
        mock_enviar.return_value = (True, "")

        enviar_whatsapp_task.delay(self.contrato.pk)

        mock_enviar.assert_called_once_with(self.contrato)

    @patch("gestao_contratos.services.whatsapp.enviar_whatsapp_contrato")
    def test_recupera_apos_falha_temporaria(self, mock_enviar: MagicMock) -> None:
        mock_enviar.side_effect = [(False, "timeout"), (True, "")]

        enviar_whatsapp_task.delay(self.contrato.pk)

        self.assertEqual(mock_enviar.call_count, 2)

    @patch("gestao_contratos.services.whatsapp.enviar_whatsapp_contrato")
    def test_falha_persistente_esgota_tentativas_sem_propagar(
        self, mock_enviar: MagicMock
    ) -> None:
        mock_enviar.return_value = (False, "Z-API fora do ar")

        enviar_whatsapp_task.delay(self.contrato.pk)

        self.assertEqual(mock_enviar.call_count, 6)

    def test_contrato_inexistente_nao_chama_a_api(self) -> None:
        with patch(
            "gestao_contratos.services.whatsapp.enviar_whatsapp_contrato"
        ) as mock_enviar:
            enviar_whatsapp_task.delay(999_999)
            mock_enviar.assert_not_called()


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — views de ação da pós-geração
# ---------------------------------------------------------------------------


class PosGeracaoActionViewsTests(AssinaturaBaseTests):
    """Download, e-mail, WhatsApp manual e envio ao Dental — sem nenhuma
    cobertura anterior apesar de serem os fluxos mais usados pelo staff."""

    def test_baixar_docx(self) -> None:
        response = self.client.get(reverse("contrato_baixar", args=[self.contrato.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_baixar_docx_sem_arquivo_redireciona(self) -> None:
        self.contrato.arquivo = None
        self.contrato.save(update_fields=["arquivo"])

        response = self.client.get(reverse("contrato_baixar", args=[self.contrato.pk]))

        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_enviar_email_sucesso(self) -> None:
        response = self.client.post(
            reverse("contrato_enviar_email", args=[self.contrato.pk]),
            data={"email_destinatario": "paciente@example.com"},
            follow=True,
        )

        self.assertContains(response, "enviado com sucesso")
        self.assertEqual(len(mail.outbox), 1)
        self.pac.refresh_from_db()
        self.assertEqual(self.pac.email, "paciente@example.com")

    def test_enviar_email_sem_destinatario(self) -> None:
        response = self.client.post(
            reverse("contrato_enviar_email", args=[self.contrato.pk]),
            data={"email_destinatario": ""},
            follow=True,
        )
        self.assertContains(response, "Informe um e-mail válido")

    def test_enviar_email_get_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_enviar_email", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    @patch("gestao_contratos.views.enviar_contrato_email")
    def test_enviar_email_falha_exibe_erro(self, mock_enviar: MagicMock) -> None:
        mock_enviar.return_value = False

        response = self.client.post(
            reverse("contrato_enviar_email", args=[self.contrato.pk]),
            data={"email_destinatario": "paciente@example.com"},
            follow=True,
        )

        self.assertContains(response, "Não foi possível enviar o e-mail")

    def test_whatsapp_status_numero_valido(self) -> None:
        response = self.client.post(
            reverse("contrato_whatsapp_status", args=[self.contrato.pk]),
            data={"celular": "62999998888"},
            follow=True,
        )

        self.assertContains(response, "marcado como enviado")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "enviado_whatsapp")

    def test_whatsapp_status_numero_invalido_nao_marca_enviado(self) -> None:
        """Regressão: número inválido não pode marcar o contrato como
        enviado — nada foi de fato encaminhado."""
        response = self.client.post(
            reverse("contrato_whatsapp_status", args=[self.contrato.pk]),
            data={"celular": ""},
            follow=True,
        )

        self.assertContains(response, "Número de telefone inválido")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "nao_enviado")
        self.assertIsNone(self.contrato.enviado_em)

    def test_whatsapp_status_get_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_whatsapp_status", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    @patch("gestao_contratos.views.enviar_contrato_ao_dental")
    def test_enviar_ao_dental_sucesso(self, mock_enviar: MagicMock) -> None:
        mock_enviar.return_value = (True, "")
        self.contrato.status = "assinado"
        self.contrato.save(update_fields=["status"])

        response = self.client.post(
            reverse("contrato_enviar_dental", args=[self.contrato.pk]), follow=True
        )

        self.assertContains(response, "enviado com sucesso")

    @patch("gestao_contratos.views.enviar_contrato_ao_dental")
    def test_enviar_ao_dental_falha(self, mock_enviar: MagicMock) -> None:
        mock_enviar.return_value = (False, "erro simulado")
        self.contrato.status = "assinado"
        self.contrato.save(update_fields=["status"])

        response = self.client.post(
            reverse("contrato_enviar_dental", args=[self.contrato.pk]), follow=True
        )

        self.assertContains(response, "Falha ao enviar o contrato")
        self.assertContains(response, "erro simulado")

    @patch("gestao_contratos.views.enviar_contrato_ao_dental")
    def test_enviar_ao_dental_bloqueado_sem_assinatura(
        self, mock_enviar: MagicMock
    ) -> None:
        """Regressão: contrato não assinado não pode ir ao Dental Office —
        o serviço cairia no PDF sem assinatura e arquivaria um documento
        sem valor na ficha do paciente."""
        response = self.client.post(
            reverse("contrato_enviar_dental", args=[self.contrato.pk]), follow=True
        )

        self.assertContains(response, "ainda não foi assinado")
        mock_enviar.assert_not_called()

    def test_pos_geracao_desabilita_envio_dental_sem_assinatura(self) -> None:
        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertContains(response, "Disponível após a assinatura do paciente")

    def test_pos_geracao_habilita_envio_dental_apos_assinatura(self) -> None:
        self.contrato.status = "assinado"
        self.contrato.save(update_fields=["status"])

        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertNotContains(response, "Disponível após a assinatura do paciente")
        self.assertContains(response, "Enviar ao Dental Office")

    def test_enviar_ao_dental_get_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_enviar_dental", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response, reverse("contratos"), fetch_redirect_response=False
        )


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — link manual de WhatsApp (envio.py)
# ---------------------------------------------------------------------------


class WhatsappLinkTests(AssinaturaBaseTests):
    def test_calcular_link_com_numero_valido(self) -> None:
        from gestao_contratos.services.envio import calcular_link_whatsapp

        link = calcular_link_whatsapp("62999998888", "Modelo 1")

        self.assertTrue(link.startswith("https://wa.me/5562999998888"))

    def test_calcular_link_com_numero_invalido_retorna_vazio(self) -> None:
        from gestao_contratos.services.envio import calcular_link_whatsapp

        self.assertEqual(calcular_link_whatsapp("", "Modelo 1"), "")

    def test_gerar_link_marca_contrato_como_enviado(self) -> None:
        from gestao_contratos.services.envio import gerar_link_whatsapp

        link = gerar_link_whatsapp("62999998888", self.contrato)

        self.assertTrue(link)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "enviado_whatsapp")
        self.assertIsNotNone(self.contrato.enviado_em)

    def test_gerar_link_com_numero_invalido_nao_marca_contrato(self) -> None:
        """Regressão: número inválido não deve marcar o contrato como
        enviado — antes desta correção, o status era sempre sobrescrito."""
        from gestao_contratos.services.envio import gerar_link_whatsapp

        link = gerar_link_whatsapp("", self.contrato)

        self.assertEqual(link, "")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "nao_enviado")
        self.assertIsNone(self.contrato.enviado_em)


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — e-mail: fallback DOCX e falhas
# ---------------------------------------------------------------------------


class EnviarContratoEmailEdgeCasesTests(AssinaturaBaseTests):
    def test_usa_docx_quando_nao_ha_nenhum_pdf(self) -> None:
        from gestao_contratos.services.envio import enviar_contrato_email

        self.contrato.arquivo_pdf = None
        self.contrato.arquivo_pdf_assinado = None
        self.contrato.save(update_fields=["arquivo_pdf", "arquivo_pdf_assinado"])

        ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertTrue(ok)
        nome, _, content_type = mail.outbox[0].attachments[0]
        self.assertTrue(nome.endswith(".docx"))
        self.assertEqual(
            content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_sem_nenhum_arquivo_retorna_false(self) -> None:
        from gestao_contratos.services.envio import enviar_contrato_email

        self.contrato.arquivo = None
        self.contrato.arquivo_pdf = None
        self.contrato.arquivo_pdf_assinado = None
        self.contrato.save(
            update_fields=["arquivo", "arquivo_pdf", "arquivo_pdf_assinado"]
        )

        ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertFalse(ok)
        self.assertEqual(len(mail.outbox), 0)

    def test_docx_ilegivel_retorna_false(self) -> None:
        import os

        from gestao_contratos.services.envio import enviar_contrato_email

        self.contrato.arquivo_pdf = None
        self.contrato.arquivo_pdf_assinado = None
        self.contrato.save(update_fields=["arquivo_pdf", "arquivo_pdf_assinado"])
        os.remove(self.contrato.arquivo.path)

        ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertFalse(ok)

    def test_pdf_assinado_ilegivel_cai_para_original(self) -> None:
        import os

        from django.core.files.base import ContentFile

        self.contrato.arquivo_pdf_assinado.save(
            "assinado.pdf", ContentFile(b"%PDF-fake-assinado"), save=True
        )
        caminho_assinado = self.contrato.arquivo_pdf_assinado.path
        os.remove(caminho_assinado)

        from gestao_contratos.services.documentos import obter_melhor_pdf_bytes

        conteudo = obter_melhor_pdf_bytes(self.contrato)

        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertNotEqual(conteudo, b"%PDF-fake-assinado")

    def test_falha_no_envio_smtp_retorna_false(self) -> None:
        from gestao_contratos.services.envio import enviar_contrato_email

        with patch("gestao_contratos.services.envio.EmailMessage") as MockEmailMessage:
            MockEmailMessage.return_value.send.side_effect = Exception(
                "SMTP indisponível"
            )
            ok = enviar_contrato_email(self.contrato, "paciente@example.com")

        self.assertFalse(ok)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_envio, "nao_enviado")


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — geração de documentos, combinações de dados
# ---------------------------------------------------------------------------


class GeracaoDocumentosEdgeCasesTests(TestCase):
    def test_docx_com_rg_sem_cpf(self) -> None:
        pac = _paciente(id_dental="D1", rg="1234567", nome="Paciente RG")
        conteudo = gerar_contrato(paciente=pac, tipo="modelo_1")
        self.assertTrue(conteudo.startswith(b"PK"))  # DOCX é um zip

    def test_pdf_com_rg_sem_cpf(self) -> None:
        pac = _paciente(id_dental="D2", rg="1234567", nome="Paciente RG")
        conteudo = gerar_pdf(paciente=pac, tipo="modelo_1")
        self.assertTrue(conteudo.startswith(b"%PDF"))

    def test_docx_com_responsavel_legal(self) -> None:
        pac = _paciente(
            id_dental="D3",
            cpf="111.222.333-44",
            nome_responsavel="Mãe Responsável",
            cpf_responsavel="999.888.777-66",
        )
        conteudo = gerar_contrato(paciente=pac, tipo="modelo_2")
        self.assertTrue(conteudo.startswith(b"PK"))

    def test_pdf_com_responsavel_legal(self) -> None:
        pac = _paciente(
            id_dental="D4",
            cpf="111.222.333-44",
            nome_responsavel="Mãe Responsável",
            cpf_responsavel="999.888.777-66",
        )
        conteudo = gerar_pdf(paciente=pac, tipo="modelo_2")
        self.assertTrue(conteudo.startswith(b"%PDF"))

    def test_docx_sem_endereco(self) -> None:
        pac = _paciente(id_dental="D5", cpf="111.222.333-44")
        conteudo = gerar_contrato(paciente=pac, tipo="modelo_1")
        self.assertTrue(conteudo.startswith(b"PK"))

    def test_pdf_sem_endereco(self) -> None:
        pac = _paciente(id_dental="D6", cpf="111.222.333-44")
        conteudo = gerar_pdf(paciente=pac, tipo="modelo_1")
        self.assertTrue(conteudo.startswith(b"%PDF"))

    def _paciente_endereco_completo(self, id_dental: str):
        return _paciente(
            id_dental=id_dental,
            cpf="111.222.333-44",
            endereco_logradouro="Avenida Goiás",
            endereco_numero="123",
            endereco_complemento="Apto 45",
            endereco_bairro="Setor Central",
            endereco_cidade="Goiânia",
            endereco_estado="GO",
            endereco_cep="74000-000",
        )

    def test_docx_com_endereco_completo_e_cro(self) -> None:
        pac = self._paciente_endereco_completo("D7")
        conteudo = gerar_contrato(
            paciente=pac, tipo="modelo_1", profissional_cro="CRO-GO 12345"
        )
        self.assertTrue(conteudo.startswith(b"PK"))

    def test_pdf_com_endereco_completo_e_cro(self) -> None:
        pac = self._paciente_endereco_completo("D8")
        conteudo = gerar_pdf(
            paciente=pac, tipo="modelo_1", profissional_cro="CRO-GO 12345"
        )
        self.assertTrue(conteudo.startswith(b"%PDF"))

    def test_pdf_com_valor_longo_quebra_linha(self) -> None:
        """Cobre o fallback de quebra de linha do helper campo() no PDF,
        quando o valor não cabe na largura disponível ao lado do rótulo."""
        pac = _paciente(
            id_dental="D9",
            cpf="111.222.333-44",
            endereco_logradouro="Rua " + ("Muito Longa " * 20),
            endereco_cidade="Goiânia",
            endereco_estado="GO",
        )
        conteudo = gerar_pdf(paciente=pac, tipo="modelo_1")
        self.assertTrue(conteudo.startswith(b"%PDF"))


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — validação da imagem de assinatura
# ---------------------------------------------------------------------------


class ValidarPngEdgeCasesTests(TestCase):
    def test_data_url_vazia(self) -> None:
        with self.assertRaises(AssinaturaInvalida):
            _validar_png("")

    def test_base64_invalido(self) -> None:
        with self.assertRaises(AssinaturaInvalida):
            _validar_png("data:image/png;base64,***invalido***")

    def test_imagem_maior_que_limite(self) -> None:
        from gestao_contratos.services import assinatura as assinatura_mod

        grande = base64.b64encode(b"0" * (assinatura_mod._ASSINATURA_MAX_BYTES + 1))
        with self.assertRaises(AssinaturaInvalida):
            _validar_png("data:image/png;base64," + grande.decode())

    def test_imagem_nao_e_png(self) -> None:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (200, 100), (255, 0, 0)).save(buf, format="JPEG")
        dado = base64.b64encode(buf.getvalue()).decode()
        with self.assertRaises(AssinaturaInvalida):
            _validar_png("data:image/jpeg;base64," + dado)

    def test_imagem_muito_pequena(self) -> None:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (20, 10), (0, 0, 0, 0)).save(buf, format="PNG")
        dado = base64.b64encode(buf.getvalue()).decode()
        with self.assertRaises(AssinaturaInvalida):
            _validar_png("data:image/png;base64," + dado)


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — casos de borda de assinatura.py
# ---------------------------------------------------------------------------


class ResolverTokenEdgeCasesTests(AssinaturaBaseTests):
    def test_token_valido_mas_sessao_removida(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        sessao.delete()

        with self.assertRaises(SessaoInvalida) as ctx:
            resolver_token(token)
        self.assertEqual(ctx.exception.motivo, "invalida")

    def test_sessao_ja_marcada_expirada_no_banco(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        sessao.status = "expirada"
        sessao.save(update_fields=["status"])

        with self.assertRaises(SessaoInvalida) as ctx:
            resolver_token(token)
        self.assertEqual(ctx.exception.motivo, "expirada")

    def test_expirar_se_vencida_ainda_no_prazo_nao_expira(self) -> None:
        from gestao_contratos.services.assinatura import expirar_se_vencida

        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        self.assertFalse(expirar_se_vencida(sessao))
        sessao.refresh_from_db()
        self.assertEqual(sessao.status, "pendente")

    def test_expirar_se_vencida_em_status_terminal_e_no_op(self) -> None:
        from gestao_contratos.services.assinatura import expirar_se_vencida

        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        sessao.status = "cancelada"
        sessao.save(update_fields=["status"])

        self.assertFalse(expirar_se_vencida(sessao))


class ObterPdfOriginalEdgeCaseTests(AssinaturaBaseTests):
    def test_arquivo_ilegivel_regenera_pdf(self) -> None:
        import os

        from gestao_contratos.services.assinatura import _obter_pdf_original

        caminho = self.contrato.arquivo_pdf.path
        os.remove(caminho)

        conteudo = _obter_pdf_original(self.contrato)

        self.assertTrue(conteudo.startswith(b"%PDF"))

    def test_sem_nome_de_arquivo_usa_fallback_no_pos_assinatura(self) -> None:
        self.contrato.arquivo_pdf = None
        self.contrato.save(update_fields=["arquivo_pdf"])
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        contrato = processar_assinatura(
            sessao, _assinatura_data_url(), ip=None, user_agent=""
        )

        self.assertIn(f"contrato_{contrato.pk}", contrato.arquivo_pdf_assinado.name)


class RegistrarAberturaEdgeCaseTests(AssinaturaBaseTests):
    def test_nao_reabre_sessao_ja_aberta(self) -> None:
        from gestao_contratos.services.assinatura import registrar_abertura

        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        sessao.status = "aberta"
        sessao.aberta_em = timezone.now()
        sessao.save(update_fields=["status", "aberta_em"])
        eventos_antes = EventoContrato.objects.filter(
            sessao=sessao, tipo="contrato_aberto"
        ).count()

        registrar_abertura(sessao)

        eventos_depois = EventoContrato.objects.filter(
            sessao=sessao, tipo="contrato_aberto"
        ).count()
        self.assertEqual(eventos_antes, eventos_depois)


class ProcessarAssinaturaFalhaNaGeracaoTests(AssinaturaBaseTests):
    @patch("gestao_contratos.services.assinatura_pdf.aplicar_assinatura_no_pdf")
    def test_falha_ao_gerar_pdf_reverte_o_claim(self, mock_aplicar: MagicMock) -> None:
        mock_aplicar.side_effect = RuntimeError("falha ao mesclar PDF")
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        with self.assertRaises(RuntimeError):
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        sessao.refresh_from_db()
        self.assertEqual(sessao.status, "aberta")
        self.assertIsNone(sessao.assinada_em)
        self.contrato.refresh_from_db()
        self.assertNotEqual(self.contrato.status, "assinado")


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — envio_dental.py: regeneração e erro no corpo
# ---------------------------------------------------------------------------


class EnviarDentalEdgeCasesTests(AssinaturaBaseTests):
    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_regenera_pdf_quando_nao_ha_arquivo_salvo(
        self, MockDental: MagicMock
    ) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.contrato.arquivo_pdf = None
        self.contrato.arquivo_pdf_assinado = None
        self.contrato.save(update_fields=["arquivo_pdf", "arquivo_pdf_assinado"])
        MockDental.return_value.enviar_documento_paciente.return_value = {"id": 1}

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertTrue(ok)
        kwargs = MockDental.return_value.enviar_documento_paciente.call_args.kwargs
        self.assertTrue(kwargs["arquivo_bytes"].startswith(b"%PDF"))

    def test_falha_ao_regenerar_pdf_retorna_erro(self) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        self.contrato.arquivo_pdf = None
        self.contrato.arquivo_pdf_assinado = None
        self.contrato.save(update_fields=["arquivo_pdf", "arquivo_pdf_assinado"])

        with patch(
            "gestao_contratos.services.envio_dental.gerar_pdf",
            side_effect=RuntimeError("modelo corrompido"),
        ):
            ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertFalse(ok)
        self.assertIn("modelo corrompido", erro)

    @patch("gestao_contratos.services.envio_dental.DentalClient")
    def test_erro_no_corpo_da_resposta_com_lista(self, MockDental: MagicMock) -> None:
        from gestao_contratos.services.envio_dental import enviar_contrato_ao_dental

        MockDental.return_value.enviar_documento_paciente.return_value = {
            "errors": ["nome muito longo", "arquivo inválido"]
        }

        ok, erro = enviar_contrato_ao_dental(self.contrato)

        self.assertFalse(ok)
        self.assertIn("nome muito longo", erro)
        self.assertIn("arquivo inválido", erro)


class ExtrairErroRespostaTests(TestCase):
    def test_resposta_nao_dict_retorna_vazio(self) -> None:
        from gestao_contratos.services.envio_dental import _extrair_erro_resposta

        self.assertEqual(_extrair_erro_resposta("string qualquer"), "")
        self.assertEqual(_extrair_erro_resposta(None), "")

    def test_chave_error_como_string(self) -> None:
        from gestao_contratos.services.envio_dental import _extrair_erro_resposta

        self.assertEqual(
            _extrair_erro_resposta({"error": "falha pontual"}), "falha pontual"
        )

    def test_sem_chaves_de_erro_retorna_vazio(self) -> None:
        from gestao_contratos.services.envio_dental import _extrair_erro_resposta

        self.assertEqual(
            _extrair_erro_resposta({"message": "Document created successfully"}), ""
        )


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — views_assinatura.py: rate-limit e guardas
# ---------------------------------------------------------------------------


class ViewsAssinaturaEdgeCasesTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_ip_via_x_forwarded_for(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        self.client.logout()

        response = self.client.get(
            reverse("assinatura_publica", args=[token]),
            HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1",
        )

        self.assertEqual(response.status_code, 200)

    def test_rate_limit_excedido_retorna_429(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        self.client.logout()
        url = reverse("assinatura_publica", args=[token])

        chave = "assinatura_rl_assinar_127.0.0.1"
        cache.set(chave, 30, 60)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 429)

    def test_pdf_publico_com_token_invalido_retorna_404(self) -> None:
        self.client.logout()
        response = self.client.get(
            reverse("assinatura_publica_pdf", args=["token-invalido"])
        )
        self.assertEqual(response.status_code, 404)

    def test_iniciar_assinatura_get_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_iniciar_assinatura_ja_assinado_nao_cria_sessao(self) -> None:
        self.contrato.status = "assinado"
        self.contrato.save(update_fields=["status"])

        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            follow=True,
        )

        self.assertContains(response, "já foi assinado")
        self.assertIsNone(sessao_ativa(self.contrato))

    def test_cancelar_assinatura_get_redireciona(self) -> None:
        response = self.client.get(
            reverse("contrato_cancelar_assinatura", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_cancelar_assinatura_com_next_redireciona_para_destino(self) -> None:
        # Usado pelo link "Editar dados do paciente" na pós-geração: cancela
        # a sessão em andamento e já segue direto para a edição, em vez de
        # voltar para a própria pós-geração.
        criar_sessao(self.contrato, criado_por=self.usuario)
        destino = reverse("contrato_gerar", args=[self.contrato.paciente.pk])

        response = self.client.post(
            reverse("contrato_cancelar_assinatura", args=[self.contrato.pk]),
            data={"next": destino},
        )

        self.assertRedirects(response, destino, fetch_redirect_response=False)
        self.assertIsNone(sessao_ativa(self.contrato))

    def test_cancelar_assinatura_com_next_externo_e_ignorado(self) -> None:
        # Só aceita caminhos locais (começando com "/") — evita redirect
        # aberto caso "next" venha manipulado.
        criar_sessao(self.contrato, criado_por=self.usuario)

        response = self.client.post(
            reverse("contrato_cancelar_assinatura", args=[self.contrato.pk]),
            data={"next": "https://evil.example.com/"},
        )

        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_pdf_publico_rate_limit_excedido(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        self.client.logout()
        cache.set("assinatura_rl_pdf_127.0.0.1", 30, 60)

        response = self.client.get(reverse("assinatura_publica_pdf", args=[token]))

        self.assertEqual(response.status_code, 429)

    def test_rate_limit_recupera_de_condicao_de_corrida_no_incr(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        token = gerar_token(sessao)
        self.client.logout()

        with patch(
            "gestao_contratos.views_assinatura.cache.incr",
            side_effect=ValueError,
        ):
            response = self.client.get(reverse("assinatura_publica", args=[token]))

        self.assertEqual(response.status_code, 200)

    @patch("gestao_contratos.views_assinatura.processar_assinatura")
    def test_post_sessaoinvalida_durante_processamento_retorna_410(
        self, mock_processar: MagicMock
    ) -> None:
        mock_processar.side_effect = SessaoInvalida("ja_assinada")
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        _confirmar_identidade_sessao(sessao)
        token = gerar_token(sessao)
        self.client.logout()

        response = self.client.post(
            reverse("assinatura_publica", args=[token]),
            data={"assinatura": _assinatura_data_url()},
        )

        self.assertEqual(response.status_code, 410)


class IpDoRequestTests(TestCase):
    """A-02: o IP gravado no PDF e na auditoria não pode ser escolhido pelo cliente.

    O ``X-Forwarded-For`` cresce da esquerda para a direita e cada proxy
    acrescenta o endereço de quem falou com ele — então a entrada mais à
    esquerda é a que o cliente mandou, e a mais à direita é a que o proxy de
    borda (confiável) acrescentou.
    """

    def setUp(self) -> None:
        from django.test import RequestFactory

        self.factory = RequestFactory()

    def _ip(self, **meta: str) -> str | None:
        from gestao_contratos.views_assinatura import _ip_do_request

        return _ip_do_request(self.factory.get("/", **meta))

    def test_sem_cabecalho_usa_o_endereco_da_conexao(self) -> None:
        self.assertEqual(self._ip(REMOTE_ADDR="203.0.113.9"), "203.0.113.9")

    @override_settings(PROXIES_CONFIAVEIS=1)
    def test_ignora_o_valor_forjado_pelo_cliente(self) -> None:
        # "9.9.9.9" é o que o cliente enviou; "203.0.113.9" foi acrescentado
        # pelo proxy de borda e é o endereço real.
        self.assertEqual(
            self._ip(
                HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.9",
                REMOTE_ADDR="10.0.0.1",
            ),
            "203.0.113.9",
        )

    @override_settings(PROXIES_CONFIAVEIS=1)
    def test_cabecalho_com_um_valor_so(self) -> None:
        self.assertEqual(
            self._ip(HTTP_X_FORWARDED_FOR="203.0.113.9", REMOTE_ADDR="10.0.0.1"),
            "203.0.113.9",
        )

    @override_settings(PROXIES_CONFIAVEIS=2)
    def test_respeita_a_quantidade_de_proxies_declarada(self) -> None:
        self.assertEqual(
            self._ip(
                HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.9, 10.0.0.2",
                REMOTE_ADDR="10.0.0.1",
            ),
            "203.0.113.9",
        )

    @override_settings(PROXIES_CONFIAVEIS=2)
    def test_entradas_de_menos_caem_no_endereco_da_conexao(self) -> None:
        # Menos saltos do que o esperado: a requisição não veio pelo caminho
        # previsto, então o cabeçalho não é confiável.
        self.assertEqual(
            self._ip(HTTP_X_FORWARDED_FOR="9.9.9.9", REMOTE_ADDR="10.0.0.1"),
            "10.0.0.1",
        )

    @override_settings(PROXIES_CONFIAVEIS=0)
    def test_sem_proxy_confiavel_o_cabecalho_e_ignorado(self) -> None:
        self.assertEqual(
            self._ip(
                HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.9",
                REMOTE_ADDR="10.0.0.1",
            ),
            "10.0.0.1",
        )


# ---------------------------------------------------------------------------
# Cobertura adicional (Fase 6) — __str__ dos modelos e checklist
# ---------------------------------------------------------------------------


class ModelosStrTests(AssinaturaBaseTests):
    def test_sessao_assinatura_str(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        texto = str(sessao)
        self.assertIn(f"Sessão #{sessao.pk}", texto)
        self.assertIn("pendente", texto)

    def test_sessao_assinatura_ativa(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        self.assertTrue(sessao.ativa)
        sessao.status = "assinada"
        sessao.save(update_fields=["status"])
        self.assertFalse(sessao.ativa)

    def test_evento_contrato_str(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        evento = EventoContrato.objects.filter(
            contrato=self.contrato, sessao=sessao
        ).first()
        self.assertIn("contrato", str(evento))
        self.assertIn(str(self.contrato.pk), str(evento))


class ChecklistEdgeCasesTests(TestCase):
    def test_bloqueado_true_com_pendencias(self) -> None:
        pac = _paciente(id_dental="CH1")
        self.assertTrue(bloqueado(pac))

    def test_bloqueado_false_sem_pendencias(self) -> None:
        pac = _paciente_completo(id_dental="CH2")
        self.assertFalse(bloqueado(pac))

    def test_menor_com_aniversario_ainda_nao_ocorrido_no_ano(self) -> None:
        """Cobre o ramo em que o aniversário deste ano ainda não chegou."""
        hoje = date.today()
        proximo_mes = 12 if hoje.month == 12 else hoje.month + 1
        nascimento = date(hoje.year - 10, proximo_mes, 1)
        pac = _paciente(
            id_dental="CH3",
            data_nascimento=nascimento,
            cpf="111.222.333-44",
            endereco_cidade="Goiânia",
        )
        itens = gerar_checklist(pac)
        item_resp = next(
            i for i in itens if "Responsável" in i.rotulo and "nome" in i.rotulo
        )
        self.assertTrue(item_resp.obrigatorio)  # confirma que foi tratado como menor


# ---------------------------------------------------------------------------
# Carimbo de tempo (RFC 3161)
# ---------------------------------------------------------------------------

_TSA_URL = "https://freetsa.org/tsr"


class CarimboTempoConfigTests(TestCase):
    @override_settings(CARIMBO_TEMPO_TSA_URL="")
    def test_sem_tsa_url_fica_desativado(self) -> None:
        self.assertIsNone(carregar_config_carimbo_tempo())
        self.assertFalse(carimbo_tempo_configurado())

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_com_tsa_url_fica_ativado(self) -> None:
        config = carregar_config_carimbo_tempo()
        self.assertIsNotNone(config)
        self.assertEqual(config.url, _TSA_URL)
        self.assertEqual(config.timeout, 30)
        self.assertTrue(carimbo_tempo_configurado())

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="user",
        CARIMBO_TEMPO_TSA_PASSWORD="pass",
        CARIMBO_TEMPO_TIMEOUT=45,
    )
    def test_credenciais_e_timeout_customizados(self) -> None:
        config = carregar_config_carimbo_tempo()
        self.assertEqual(config.username, "user")
        self.assertEqual(config.password, "pass")
        self.assertEqual(config.timeout, 45)


class SolicitarCarimboTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")
        self.contrato.refresh_from_db()

    def test_sem_tsa_configurada_retorna_erro_sem_solicitar(self) -> None:
        with override_settings(CARIMBO_TEMPO_TSA_URL=""):
            ok, erro = solicitar_carimbo(self.contrato)

        self.assertFalse(ok)
        self.assertIn("não configurado", erro)
        self.assertFalse(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="carimbo_tempo_iniciado"
            ).exists()
        )

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_sem_hash_calculado_marca_erro(self) -> None:
        self.contrato.hash_sha256 = ""
        self.contrato.save(update_fields=["hash_sha256"])

        ok, erro = solicitar_carimbo(self.contrato)

        self.assertFalse(ok)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_carimbo_tempo, "erro")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="carimbo_tempo_erro"
            ).exists()
        )

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    @patch("rfc3161ng.get_timestamp")
    @patch("rfc3161ng.RemoteTimestamper")
    def test_sucesso_salva_token_e_data_atestada(
        self, MockTimestamper: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        from datetime import datetime as dt

        from pypdf import PdfReader

        hash_antes_do_carimbo = self.contrato.hash_sha256

        MockTimestamper.return_value.timestamp.return_value = b"token-tsr-fake"
        mock_get_timestamp.return_value = dt(2026, 7, 6, 12, 0, 0)

        ok, erro = solicitar_carimbo(self.contrato)

        self.assertTrue(ok)
        self.assertEqual(erro, "")
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_carimbo_tempo, "concluido")
        self.assertEqual(self.contrato.carimbo_tempo_tsa, _TSA_URL)
        self.assertEqual(
            self.contrato.carimbo_tempo_em.isoformat(), "2026-07-06T12:00:00+00:00"
        )
        self.contrato.carimbo_tempo.open("rb")
        conteudo = self.contrato.carimbo_tempo.read()
        self.contrato.carimbo_tempo.close()
        self.assertEqual(conteudo, b"token-tsr-fake")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="carimbo_tempo_concluido"
            ).exists()
        )

        # O PDF assinado passa a levar o token embutido como anexo — o
        # hash salvo continua sendo o que a TSA efetivamente atestou
        # (calculado antes deste anexo), e não deve mudar.
        self.assertEqual(self.contrato.hash_sha256, hash_antes_do_carimbo)
        self.contrato.arquivo_pdf_assinado.open("rb")
        pdf_bytes = self.contrato.arquivo_pdf_assinado.read()
        self.contrato.arquivo_pdf_assinado.close()
        leitor = PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(leitor.attachments["carimbo_tempo.tsr"], [b"token-tsr-fake"])
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    @patch("rfc3161ng.RemoteTimestamper")
    def test_falha_na_tsa_marca_erro(self, MockTimestamper: MagicMock) -> None:
        MockTimestamper.return_value.timestamp.side_effect = RuntimeError(
            "TSA indisponível"
        )

        ok, erro = solicitar_carimbo(self.contrato)

        self.assertFalse(ok)
        self.assertIn("TSA indisponível", erro)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_carimbo_tempo, "erro")
        self.assertTrue(
            EventoContrato.objects.filter(
                contrato=self.contrato, tipo="carimbo_tempo_erro"
            ).exists()
        )

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    @patch("rfc3161ng.get_timestamp")
    @patch("rfc3161ng.RemoteTimestamper")
    def test_sucesso_sem_pdf_assinado_nao_quebra(
        self, MockTimestamper: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        """Defensivo: sem PDF assinado salvo (não deveria ocorrer na prática,
        já que solicitar_carimbo só é chamada após a assinatura), o carimbo
        em si continua sendo obtido e salvo normalmente."""
        from datetime import datetime as dt

        self.contrato.arquivo_pdf_assinado.delete(save=True)

        MockTimestamper.return_value.timestamp.return_value = b"token-tsr-fake"
        mock_get_timestamp.return_value = dt(2026, 7, 6, 12, 0, 0)

        ok, erro = solicitar_carimbo(self.contrato)

        self.assertTrue(ok)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status_carimbo_tempo, "concluido")
        self.assertFalse(self.contrato.arquivo_pdf_assinado)


class SolicitarCarimboTempoTaskTests(TestCase):
    """Testa solicitar_carimbo_tempo_task diretamente — sem herdar de
    AssinaturaBaseTests, já que aquela base não mocka esta tarefa (o
    carimbo só é agendado quando configurado, o que os testes de
    assinatura não fazem por padrão)."""

    def setUp(self) -> None:
        self.usuario = _usuario()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="702")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )

    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_sucesso_chama_uma_unica_vez(self, mock_solicitar: MagicMock) -> None:
        mock_solicitar.return_value = (True, "")

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        mock_solicitar.assert_called_once_with(self.contrato)

    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_recupera_apos_falha_temporaria(self, mock_solicitar: MagicMock) -> None:
        mock_solicitar.side_effect = [(False, "timeout"), (True, "")]

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        self.assertEqual(mock_solicitar.call_count, 2)

    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_falha_persistente_esgota_tentativas_sem_propagar(
        self, mock_solicitar: MagicMock
    ) -> None:
        mock_solicitar.return_value = (False, "TSA fora do ar")

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        self.assertEqual(mock_solicitar.call_count, 6)

    def test_contrato_inexistente_nao_chama_o_servico(self) -> None:
        with patch(
            "gestao_contratos.services.carimbo_tempo.solicitar_carimbo"
        ) as mock_solicitar:
            solicitar_carimbo_tempo_task.delay(999_999)
            mock_solicitar.assert_not_called()


class CarimboAntesDoEnvioTests(TestCase):
    """B-14: as cópias automáticas devem sair só depois do carimbo embutido.

    Antes, a tarefa do carimbo e as dos envios eram disparadas em paralelo
    pela assinatura — como o carimbo reescreve o PDF assinado para embutir o
    token, as cópias costumavam sair sem a prova de data/hora.
    """

    def setUp(self) -> None:
        self.usuario = _usuario()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.pac = _paciente_completo(id_dental="703")
        self.contrato = gerar_e_salvar_contrato(
            paciente=self.pac, tipo="modelo_1", gerado_por=self.usuario
        )

    @patch("gestao_contratos.services.assinatura.agendar_envios_automaticos")
    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_envios_sao_agendados_depois_do_carimbo(
        self, mock_solicitar: MagicMock, mock_agendar: MagicMock
    ) -> None:
        mock_solicitar.return_value = (True, "")
        ordem = MagicMock()
        ordem.attach_mock(mock_solicitar, "solicitar")
        ordem.attach_mock(mock_agendar, "agendar")

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        self.assertEqual(
            [chamada[0] for chamada in ordem.mock_calls], ["solicitar", "agendar"]
        )

    @patch("gestao_contratos.services.assinatura.agendar_envios_automaticos")
    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_falha_temporaria_agenda_envios_uma_vez_apos_o_sucesso(
        self, mock_solicitar: MagicMock, mock_agendar: MagicMock
    ) -> None:
        """Um retry não pode duplicar as cópias enviadas ao paciente."""
        mock_solicitar.side_effect = [(False, "timeout"), (True, "")]

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        self.assertEqual(mock_agendar.call_count, 1)

    @patch("gestao_contratos.services.assinatura.agendar_envios_automaticos")
    @patch("gestao_contratos.services.carimbo_tempo.solicitar_carimbo")
    def test_tsa_fora_do_ar_ainda_agenda_os_envios(
        self, mock_solicitar: MagicMock, mock_agendar: MagicMock
    ) -> None:
        """Reter o documento seria pior que a ausência do carimbo."""
        mock_solicitar.return_value = (False, "TSA fora do ar")

        solicitar_carimbo_tempo_task.delay(self.contrato.pk)

        self.assertEqual(mock_solicitar.call_count, 6)
        self.assertEqual(mock_agendar.call_count, 1)

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_pdf_enviado_ao_dental_carrega_o_carimbo(self) -> None:
        """Ponta a ponta: o arquivo que chega ao Dental Office leva o token.

        É a regressão que dá nome ao B-14 — com as tarefas em paralelo, este
        PDF saía sem o anexo do carimbo.
        """
        from pypdf import PdfReader

        token = b"token-tsr-de-teste"
        enviados: list[bytes] = []

        def _capturar(**kwargs) -> dict:
            enviados.append(kwargs["arquivo_bytes"])
            return {"id": "1"}

        timestamper = MagicMock()
        timestamper.timestamp.return_value = token
        client = MagicMock()
        client.enviar_documento_paciente.side_effect = _capturar

        with (
            patch("rfc3161ng.RemoteTimestamper", return_value=timestamper),
            patch(
                "rfc3161ng.get_timestamp",
                return_value=timezone.now().replace(tzinfo=None),
            ),
            patch(
                "gestao_contratos.services.envio_dental.DentalClient",
                return_value=client,
            ),
        ):
            sessao = criar_sessao(self.contrato, criado_por=self.usuario)
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.assertEqual(len(enviados), 1)
        anexos = PdfReader(io.BytesIO(enviados[0])).attachments
        self.assertIn("carimbo_tempo.tsr", anexos)
        self.assertEqual(anexos["carimbo_tempo.tsr"][0], token)


class ProcessarAssinaturaCarimboTempoTests(AssinaturaBaseTests):
    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_agenda_carimbo_quando_configurado(self) -> None:
        with patch(
            "gestao_contratos.tasks.solicitar_carimbo_tempo_task.delay"
        ) as mock_delay:
            sessao = criar_sessao(self.contrato, criado_por=self.usuario)
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        mock_delay.assert_called_once_with(self.contrato.pk)

    @override_settings(CARIMBO_TEMPO_TSA_URL="")
    def test_nao_agenda_carimbo_quando_nao_configurado(self) -> None:
        with patch(
            "gestao_contratos.tasks.solicitar_carimbo_tempo_task.delay"
        ) as mock_delay:
            sessao = criar_sessao(self.contrato, criado_por=self.usuario)
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        mock_delay.assert_not_called()

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_com_tsa_os_envios_ficam_por_conta_do_carimbo(self) -> None:
        """B-14: com TSA configurada, a assinatura não dispara mais os envios
        direto — quem os encadeia é a tarefa do carimbo, depois de embutir o
        token no PDF. Disparar aqui faria as cópias saírem sem o carimbo."""
        with patch("gestao_contratos.tasks.solicitar_carimbo_tempo_task.delay"):
            sessao = criar_sessao(self.contrato, criado_por=self.usuario)
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_dental_delay.assert_not_called()
        self.mock_enviar_whatsapp_delay.assert_not_called()

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    def test_falha_ao_enfileirar_o_carimbo_nao_perde_os_envios(self) -> None:
        """Com o broker fora do ar ninguém encadearia as cópias — a assinatura
        precisa disparar os envios ela mesma nesse caso."""
        with patch(
            "gestao_contratos.tasks.solicitar_carimbo_tempo_task.delay",
            side_effect=RuntimeError("Redis indisponível"),
        ):
            sessao = criar_sessao(self.contrato, criado_por=self.usuario)
            processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")

        self.mock_enviar_dental_delay.assert_called_once_with(self.contrato.pk)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.status, "assinado")


class CarimboTempoViewsTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        processar_assinatura(sessao, _assinatura_data_url(), ip=None, user_agent="")
        self.contrato.refresh_from_db()

    @patch("gestao_contratos.views.solicitar_carimbo")
    def test_post_sucesso_mostra_mensagem_de_sucesso(
        self, mock_solicitar: MagicMock
    ) -> None:
        mock_solicitar.return_value = (True, "")

        response = self.client.post(
            reverse("contrato_solicitar_carimbo_tempo", args=[self.contrato.pk]),
            follow=True,
        )

        self.assertContains(response, "Carimbo de tempo obtido com sucesso")

    @patch("gestao_contratos.views.solicitar_carimbo")
    def test_post_falha_mostra_mensagem_de_erro(
        self, mock_solicitar: MagicMock
    ) -> None:
        mock_solicitar.return_value = (False, "TSA indisponível")

        response = self.client.post(
            reverse("contrato_solicitar_carimbo_tempo", args=[self.contrato.pk]),
            follow=True,
        )

        self.assertContains(response, "TSA indisponível")

    def test_get_redireciona_sem_solicitar(self) -> None:
        response = self.client.get(
            reverse("contrato_solicitar_carimbo_tempo", args=[self.contrato.pk])
        )
        self.assertRedirects(
            response,
            reverse("contrato_pos_geracao", args=[self.contrato.pk]),
            fetch_redirect_response=False,
        )

    def test_baixar_sem_carimbo_redireciona_com_mensagem(self) -> None:
        response = self.client.get(
            reverse("contrato_baixar_carimbo_tempo", args=[self.contrato.pk]),
            follow=True,
        )
        self.assertContains(response, "ainda não possui carimbo de tempo")

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    @patch("rfc3161ng.get_timestamp")
    @patch("rfc3161ng.RemoteTimestamper")
    def test_baixar_com_carimbo_retorna_arquivo(
        self, MockTimestamper: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        from datetime import datetime as dt

        MockTimestamper.return_value.timestamp.return_value = b"token-tsr-fake"
        mock_get_timestamp.return_value = dt(2026, 7, 6, 12, 0, 0)
        solicitar_carimbo(self.contrato)

        response = self.client.get(
            reverse("contrato_baixar_carimbo_tempo", args=[self.contrato.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"token-tsr-fake")
        self.assertEqual(response["Content-Type"], "application/timestamp-reply")

    @override_settings(
        CARIMBO_TEMPO_TSA_URL=_TSA_URL,
        CARIMBO_TEMPO_TSA_USERNAME="",
        CARIMBO_TEMPO_TSA_PASSWORD="",
        CARIMBO_TEMPO_TIMEOUT=30,
    )
    @patch("rfc3161ng.get_timestamp")
    @patch("rfc3161ng.RemoteTimestamper")
    def test_baixar_contrato_assinado_ja_leva_o_carimbo_embutido(
        self, MockTimestamper: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        """Fim a fim: depois do carimbo, o PDF servido pelo botão normal de
        download ("Baixar contrato assinado") já é o autocontido."""
        from datetime import datetime as dt

        from pypdf import PdfReader

        MockTimestamper.return_value.timestamp.return_value = b"token-tsr-fake"
        mock_get_timestamp.return_value = dt(2026, 7, 6, 12, 0, 0)
        solicitar_carimbo(self.contrato)

        response = self.client.get(
            reverse("contrato_baixar_assinado", args=[self.contrato.pk])
        )

        self.assertEqual(response.status_code, 200)
        leitor = PdfReader(io.BytesIO(response.content))
        self.assertEqual(leitor.attachments["carimbo_tempo.tsr"], [b"token-tsr-fake"])


class PoliticaPrivacidadeViewTests(TestCase):
    def test_get_nao_exige_login_e_renderiza(self) -> None:
        response = self.client.get(reverse("contratos_politica_privacidade"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/politica_privacidade.html")
        self.assertContains(response, "Política de Privacidade")
        self.assertContains(response, "LGPD")


class AssinarLinkaPoliticaPrivacidadeTests(AssinaturaBaseTests):
    def test_rodape_linka_politica_de_privacidade(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        _confirmar_identidade_sessao(sessao)
        self.client.logout()

        response = self.client.get(
            reverse("assinatura_publica", args=[gerar_token(sessao)])
        )

        self.assertContains(response, reverse("contratos_politica_privacidade"))


# ---------------------------------------------------------------------------
# Terminal de assinatura dedicado (ex.: tablet da recepção)
# ---------------------------------------------------------------------------


class TerminalAssinaturaModelTests(TestCase):
    def test_token_gerado_automaticamente(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        self.assertTrue(terminal.token)
        self.assertGreaterEqual(len(terminal.token), 24)

    def test_tokens_sao_unicos_entre_terminais(self) -> None:
        primeiro = TerminalAssinatura.objects.create(nome="Tablet 1")
        segundo = TerminalAssinatura.objects.create(nome="Tablet 2")

        self.assertNotEqual(primeiro.token, segundo.token)

    def test_str_retorna_nome(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.assertEqual(str(terminal), "Tablet Recepção")

    def test_token_preservado_ao_salvar_novamente(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        terminal.nome = "Tablet Recepção 2"
        terminal.save()

        self.assertEqual(terminal.token, token_original)


class SessaoAtivaParaTerminalTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        self.terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

    def test_sem_sessao_retorna_none(self) -> None:
        self.assertIsNone(sessao_ativa_para_terminal(self.terminal))

    def test_sessao_do_terminal_e_retornada(self) -> None:
        sessao = criar_sessao(
            self.contrato, criado_por=self.usuario, terminal=self.terminal
        )

        self.assertEqual(sessao_ativa_para_terminal(self.terminal), sessao)

    def test_sessao_sem_terminal_nao_e_retornada(self) -> None:
        criar_sessao(self.contrato, criado_por=self.usuario)

        self.assertIsNone(sessao_ativa_para_terminal(self.terminal))

    def test_sessao_de_outro_terminal_nao_e_retornada(self) -> None:
        outro_terminal = TerminalAssinatura.objects.create(nome="Outro tablet")
        criar_sessao(self.contrato, criado_por=self.usuario, terminal=outro_terminal)

        self.assertIsNone(sessao_ativa_para_terminal(self.terminal))

    def test_sessao_vencida_expira_e_nao_e_retornada(self) -> None:
        sessao = criar_sessao(
            self.contrato, criado_por=self.usuario, terminal=self.terminal
        )
        sessao.expira_em = timezone.now() - timezone.timedelta(minutes=1)
        sessao.save(update_fields=["expira_em"])

        self.assertIsNone(sessao_ativa_para_terminal(self.terminal))
        sessao.refresh_from_db()
        self.assertEqual(sessao.status, "expirada")


class CriarSessaoComTerminalTests(AssinaturaBaseTests):
    def test_terminal_e_associado_a_sessao(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        sessao = criar_sessao(self.contrato, criado_por=self.usuario, terminal=terminal)

        self.assertEqual(sessao.terminal, terminal)

    def test_sem_terminal_fica_none(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)

        self.assertIsNone(sessao.terminal)


class TerminalAssinaturaViewTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        self.terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.client.logout()

    def test_token_invalido_retorna_404(self) -> None:
        response = self.client.get(
            reverse("terminal_assinatura", args=["token-invalido"])
        )
        self.assertEqual(response.status_code, 404)

    def test_terminal_inativo_retorna_404(self) -> None:
        self.terminal.ativo = False
        self.terminal.save(update_fields=["ativo"])

        response = self.client.get(
            reverse("terminal_assinatura", args=[self.terminal.token])
        )
        self.assertEqual(response.status_code, 404)

    def test_sem_sessao_exibe_tela_de_espera(self) -> None:
        response = self.client.get(
            reverse("terminal_assinatura", args=[self.terminal.token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/terminal_aguardando.html")
        self.assertContains(response, "Aguardando o próximo atendimento")

    def test_com_sessao_ativa_redireciona_para_assinatura(self) -> None:
        sessao = criar_sessao(
            self.contrato, criado_por=self.usuario, terminal=self.terminal
        )

        response = self.client.get(
            reverse("terminal_assinatura", args=[self.terminal.token])
        )

        self.assertRedirects(
            response,
            reverse("assinatura_publica", args=[gerar_token(sessao)]),
            fetch_redirect_response=False,
        )


class TerminalStatusFragmentViewTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        self.terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.client.logout()

    def test_sem_sessao_retorna_fragmento_de_espera(self) -> None:
        response = self.client.get(
            reverse("terminal_status_fragment", args=[self.terminal.token])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "gestao_contratos/_terminal_aguardando_fragment.html"
        )
        self.assertNotIn("HX-Redirect", response.headers)

    def test_com_sessao_envia_hx_redirect(self) -> None:
        sessao = criar_sessao(
            self.contrato, criado_por=self.usuario, terminal=self.terminal
        )

        response = self.client.get(
            reverse("terminal_status_fragment", args=[self.terminal.token])
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            reverse("assinatura_publica", args=[gerar_token(sessao)]),
        )

    def test_token_invalido_retorna_404(self) -> None:
        response = self.client.get(
            reverse("terminal_status_fragment", args=["token-invalido"])
        )
        self.assertEqual(response.status_code, 404)


class IniciarAssinaturaComTerminalTests(AssinaturaBaseTests):
    def setUp(self) -> None:
        super().setUp()
        self.terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

    def test_envia_sessao_para_terminal_escolhido(self) -> None:
        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            data={
                "identidade_presencial_confirmada": "on",
                "terminal_pk": self.terminal.pk,
            },
            follow=True,
        )

        self.assertContains(response, "Tablet Recepção")
        sessao = sessao_ativa(self.contrato)
        self.assertEqual(sessao.terminal, self.terminal)

    def test_sem_terminal_pk_gera_sessao_sem_terminal(self) -> None:
        self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            data={"identidade_presencial_confirmada": "on"},
        )

        sessao = sessao_ativa(self.contrato)
        self.assertIsNone(sessao.terminal)

    def test_terminal_pk_invalido_retorna_404(self) -> None:
        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            data={
                "identidade_presencial_confirmada": "on",
                "terminal_pk": 999_999,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertIsNone(sessao_ativa(self.contrato))

    def test_terminal_inativo_retorna_404(self) -> None:
        self.terminal.ativo = False
        self.terminal.save(update_fields=["ativo"])

        response = self.client.post(
            reverse("contrato_iniciar_assinatura", args=[self.contrato.pk]),
            data={
                "identidade_presencial_confirmada": "on",
                "terminal_pk": self.terminal.pk,
            },
        )

        self.assertEqual(response.status_code, 404)


class StatusFragmentTerminalTests(AssinaturaBaseTests):
    def test_seletor_de_terminal_aparece_quando_ha_terminais_ativos(self) -> None:
        TerminalAssinatura.objects.create(nome="Tablet Recepção")

        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertContains(response, "Onde o paciente vai assinar?")
        self.assertContains(response, "Tablet Recepção")
        self.assertContains(response, "Iniciar assinatura")

    def test_seletor_nao_aparece_sem_terminais(self) -> None:
        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertNotContains(response, "Onde o paciente vai assinar?")
        self.assertContains(response, "Gerar QR Code de assinatura")

    def test_terminal_inativo_nao_aparece_no_seletor(self) -> None:
        TerminalAssinatura.objects.create(nome="Tablet Inativo", ativo=False)

        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertNotContains(response, "Onde o paciente vai assinar?")

    def test_sessao_em_terminal_nao_mostra_qr_code(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        criar_sessao(self.contrato, criado_por=self.usuario, terminal=terminal)

        response = self.client.get(
            reverse("contrato_pos_geracao", args=[self.contrato.pk])
        )

        self.assertContains(response, "Assinatura enviada para o terminal")
        self.assertNotContains(response, "escanear o QR Code")


class AssinaturaConcluidaTerminalTests(AssinaturaBaseTests):
    def test_meta_refresh_e_mensagem_quando_sessao_tem_terminal(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        sessao = criar_sessao(self.contrato, criado_por=self.usuario, terminal=terminal)
        _confirmar_identidade_sessao(sessao)
        self.client.logout()

        response = self.client.post(
            reverse("assinatura_publica", args=[gerar_token(sessao)]),
            data={"assinatura": _assinatura_data_url()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_contratos/assinatura_concluida.html")
        self.assertContains(
            response,
            f'url={reverse("terminal_assinatura", args=[terminal.token])}',
        )
        self.assertContains(response, "Pode devolver o tablet")

    def test_sem_terminal_nao_tem_meta_refresh(self) -> None:
        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        _confirmar_identidade_sessao(sessao)
        self.client.logout()

        response = self.client.post(
            reverse("assinatura_publica", args=[gerar_token(sessao)]),
            data={"assinatura": _assinatura_data_url()},
        )

        self.assertNotContains(response, 'http-equiv="refresh"')
        self.assertContains(response, "Você já pode fechar esta página")


class TerminalAssinaturaAdminTests(TestCase):
    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            username="admin-terminal", password="senha-segura"
        )
        self.client.force_login(self.superuser)

    def test_changelist_carrega_com_link_do_terminal(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        response = self.client.get("/admin/gestao_contratos/terminalassinatura/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tablet Recepção")
        self.assertContains(
            response, reverse("terminal_assinatura", args=[terminal.token])
        )

    def test_tela_de_adicao_carrega(self) -> None:
        response = self.client.get("/admin/gestao_contratos/terminalassinatura/add/")
        self.assertEqual(response.status_code, 200)


class TerminalRegenerarTokenModelTests(TestCase):
    def test_regenerar_token_troca_o_token(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        terminal.regenerar_token()

        self.assertNotEqual(terminal.token, token_original)
        terminal.refresh_from_db()
        self.assertNotEqual(terminal.token, token_original)

    def test_regenerar_token_invalida_link_antigo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        terminal.regenerar_token()

        self.assertFalse(
            TerminalAssinatura.objects.filter(token=token_original).exists()
        )


class TerminaisStaffViewTests(TestCase):
    """Gestão de terminais pela recepção (staff logado), fora do Django Admin."""

    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_exige_login(self) -> None:
        self.client.logout()
        response = self.client.get(reverse("contrato_terminais"))
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("contrato_terminais")}',
            fetch_redirect_response=False,
        )

    def test_lista_terminais_existentes(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        response = self.client.get(reverse("contrato_terminais"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tablet Recepção")
        self.assertContains(
            response, reverse("terminal_assinatura", args=[terminal.token])
        )

    def test_cria_terminal_via_post(self) -> None:
        response = self.client.post(
            reverse("contrato_terminais"), {"nome": "Tablet Novo"}
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        self.assertTrue(TerminalAssinatura.objects.filter(nome="Tablet Novo").exists())

    def test_criar_sem_nome_nao_cria_terminal(self) -> None:
        response = self.client.post(reverse("contrato_terminais"), {"nome": ""})

        self.assertRedirects(response, reverse("contrato_terminais"))
        self.assertEqual(TerminalAssinatura.objects.count(), 0)

    def test_regenerar_token_exige_login(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.client.logout()

        url = reverse("contrato_terminal_regenerar_token", args=[terminal.pk])
        response = self.client.post(url)

        self.assertRedirects(
            response, f'{reverse("login")}?next={url}', fetch_redirect_response=False
        )

    def test_regenerar_token_via_post_gera_novo_link(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        response = self.client.post(
            reverse("contrato_terminal_regenerar_token", args=[terminal.pk])
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        terminal.refresh_from_db()
        self.assertNotEqual(terminal.token, token_original)

    def test_regenerar_token_via_get_nao_altera_nada(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        self.client.get(
            reverse("contrato_terminal_regenerar_token", args=[terminal.pk])
        )

        terminal.refresh_from_db()
        self.assertEqual(terminal.token, token_original)

    def test_alternar_ativo_desativa_terminal_ativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.assertTrue(terminal.ativo)

        response = self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[terminal.pk])
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        terminal.refresh_from_db()
        self.assertFalse(terminal.ativo)

    def test_alternar_ativo_reativa_terminal_inativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(
            nome="Tablet Recepção", ativo=False
        )

        self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[terminal.pk])
        )

        terminal.refresh_from_db()
        self.assertTrue(terminal.ativo)

    def test_link_antigo_para_de_funcionar_apos_regenerar(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        token_original = terminal.token

        self.client.post(
            reverse("contrato_terminal_regenerar_token", args=[terminal.pk])
        )

        response = self.client.get(
            reverse("terminal_assinatura", args=[token_original])
        )
        self.assertEqual(response.status_code, 404)

    def test_terminal_criado_via_post_comeca_inativo(self) -> None:
        """Novo terminal nunca nasce ativo — evita concorrer com o já ativo."""

        self.client.post(reverse("contrato_terminais"), {"nome": "Tablet Novo"})

        terminal = TerminalAssinatura.objects.get(nome="Tablet Novo")
        self.assertFalse(terminal.ativo)

    def test_nao_permite_ativar_segundo_terminal(self) -> None:
        ativo = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        outro = TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)
        self.assertTrue(ativo.ativo)

        response = self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[outro.pk])
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        outro.refresh_from_db()
        ativo.refresh_from_db()
        self.assertFalse(outro.ativo)
        self.assertTrue(ativo.ativo)

    def test_mensagem_de_erro_nomeia_o_terminal_ja_ativo(self) -> None:
        TerminalAssinatura.objects.create(nome="Tablet Recepção")
        outro = TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)

        response = self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[outro.pk]),
            follow=True,
        )

        self.assertContains(response, "Tablet Recepção")

    def test_ativar_permitido_quando_nenhum_outro_esta_ativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(
            nome="Tablet Recepção", ativo=False
        )

        response = self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[terminal.pk])
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        terminal.refresh_from_db()
        self.assertTrue(terminal.ativo)

    def test_desativar_nunca_e_bloqueado_mesmo_sendo_o_unico_ativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        self.client.post(
            reverse("contrato_terminal_alternar_ativo", args=[terminal.pk])
        )

        terminal.refresh_from_db()
        self.assertFalse(terminal.ativo)

    def test_lista_mostra_botao_ativar_desabilitado_quando_bloqueado(self) -> None:
        TerminalAssinatura.objects.create(nome="Tablet Recepção")
        TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)

        response = self.client.get(reverse("contrato_terminais"))

        self.assertContains(response, "disabled")
        self.assertContains(response, "Já existe um terminal ativo — desative-o antes")

    def test_excluir_exige_login(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.client.logout()

        url = reverse("contrato_terminal_excluir", args=[terminal.pk])
        response = self.client.post(url)

        self.assertRedirects(
            response, f'{reverse("login")}?next={url}', fetch_redirect_response=False
        )

    def test_excluir_via_post_remove_terminal(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        response = self.client.post(
            reverse("contrato_terminal_excluir", args=[terminal.pk])
        )

        self.assertRedirects(response, reverse("contrato_terminais"))
        self.assertFalse(TerminalAssinatura.objects.filter(pk=terminal.pk).exists())

    def test_excluir_via_get_nao_remove_nada(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")

        self.client.get(reverse("contrato_terminal_excluir", args=[terminal.pk]))

        self.assertTrue(TerminalAssinatura.objects.filter(pk=terminal.pk).exists())

    def test_excluir_terminal_nao_apaga_sessao_associada(self) -> None:
        pac = _paciente_completo(id_dental="777")
        contrato = gerar_e_salvar_contrato(
            paciente=pac, tipo="modelo_1", gerado_por=self.usuario
        )
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        sessao = criar_sessao(contrato, criado_por=self.usuario, terminal=terminal)

        self.client.post(reverse("contrato_terminal_excluir", args=[terminal.pk]))

        sessao.refresh_from_db()
        self.assertIsNone(sessao.terminal)
        self.assertTrue(SessaoAssinatura.objects.filter(pk=sessao.pk).exists())


class TerminalUnicoAtivoModelTests(TestCase):
    def test_outro_terminal_ativo_retorna_none_sem_conflito(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        self.assertIsNone(terminal.outro_terminal_ativo())

    def test_outro_terminal_ativo_encontra_conflito(self) -> None:
        ativo = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        outro = TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)

        self.assertEqual(outro.outro_terminal_ativo(), ativo)

    def test_clean_permite_ativar_sem_conflito(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet", ativo=False)
        terminal.ativo = True
        terminal.clean()  # não deve levantar

    def test_clean_bloqueia_segundo_ativo(self) -> None:
        TerminalAssinatura.objects.create(nome="Tablet Recepção")
        outro = TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)

        outro.ativo = True
        with self.assertRaises(ValidationError):
            outro.clean()

    def test_clean_permite_desativar_mesmo_sendo_o_unico_ativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet Recepção")
        terminal.ativo = False
        terminal.clean()  # não deve levantar

    def test_full_clean_bloqueia_via_admin_form(self) -> None:
        """Garante que a regra vale mesmo fora das views próprias (ex.:
        alguém editando ``ativo`` direto pelo Django Admin)."""

        TerminalAssinatura.objects.create(nome="Tablet Recepção")
        outro = TerminalAssinatura.objects.create(nome="Tablet Sala 2", ativo=False)

        outro.ativo = True
        with self.assertRaises(ValidationError):
            outro.full_clean()


def _forcar_ativado_ha(terminal: TerminalAssinatura, horas: float) -> None:
    """Backdata `ativado_em` para simular um terminal ativado há X horas,
    sem passar pelo detector de transição do save() (usa update_fields
    já contendo `ativado_em`, então o valor setado aqui é preservado)."""

    terminal.ativado_em = timezone.now() - timedelta(hours=horas)
    terminal.save(update_fields=["ativado_em"])


class TerminalExpiracaoAutomaticaTests(TestCase):
    def test_ativar_registra_ativado_em(self) -> None:
        antes = timezone.now()
        terminal = TerminalAssinatura.objects.create(nome="Tablet", ativo=False)

        terminal.ativo = True
        terminal.save(update_fields=["ativo", "atualizado_em"])

        terminal.refresh_from_db()
        self.assertIsNotNone(terminal.ativado_em)
        self.assertGreaterEqual(terminal.ativado_em, antes)

    def test_desativar_limpa_ativado_em(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")  # nasce ativo
        self.assertIsNotNone(terminal.ativado_em)

        terminal.ativo = False
        terminal.save(update_fields=["ativo", "atualizado_em"])

        terminal.refresh_from_db()
        self.assertIsNone(terminal.ativado_em)

    def test_expirar_se_vencido_nao_faz_nada_se_inativo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet", ativo=False)
        self.assertFalse(terminal.expirar_se_vencido())

    def test_expirar_se_vencido_nao_faz_nada_dentro_do_prazo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, TERMINAL_ATIVO_TTL_HORAS - 1)

        self.assertFalse(terminal.expirar_se_vencido())
        terminal.refresh_from_db()
        self.assertTrue(terminal.ativo)

    def test_expirar_se_vencido_desativa_apos_o_prazo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, TERMINAL_ATIVO_TTL_HORAS + 1)

        self.assertTrue(terminal.expirar_se_vencido())
        terminal.refresh_from_db()
        self.assertFalse(terminal.ativo)
        self.assertIsNone(terminal.ativado_em)

    def test_expirar_terminais_vencidos_ignora_terminal_dentro_do_prazo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, 1)

        total = expirar_terminais_vencidos()

        self.assertEqual(total, 0)
        terminal.refresh_from_db()
        self.assertTrue(terminal.ativo)

    def test_expirar_terminais_vencidos_desativa_apenas_os_vencidos(self) -> None:
        vencido = TerminalAssinatura.objects.create(nome="Vencido")
        _forcar_ativado_ha(vencido, TERMINAL_ATIVO_TTL_HORAS + 2)

        dentro_do_prazo = TerminalAssinatura.objects.create(
            nome="Dentro do prazo", ativo=False
        )

        total = expirar_terminais_vencidos()

        self.assertEqual(total, 1)
        vencido.refresh_from_db()
        dentro_do_prazo.refresh_from_db()
        self.assertFalse(vencido.ativo)
        self.assertFalse(dentro_do_prazo.ativo)  # já estava inativo, sem mudança

    def test_link_do_terminal_para_de_funcionar_apos_vencer(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, TERMINAL_ATIVO_TTL_HORAS + 1)

        response = self.client.get(
            reverse("terminal_assinatura", args=[terminal.token])
        )

        self.assertEqual(response.status_code, 404)
        terminal.refresh_from_db()
        self.assertFalse(terminal.ativo)

    def test_link_do_terminal_continua_funcionando_dentro_do_prazo(self) -> None:
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, TERMINAL_ATIVO_TTL_HORAS - 1)

        response = self.client.get(
            reverse("terminal_assinatura", args=[terminal.token])
        )

        self.assertEqual(response.status_code, 200)

    def test_lista_de_terminais_reflete_expiracao_ao_carregar(self) -> None:
        usuario = _usuario()
        self.client.force_login(usuario)
        terminal = TerminalAssinatura.objects.create(nome="Tablet")
        _forcar_ativado_ha(terminal, TERMINAL_ATIVO_TTL_HORAS + 1)

        response = self.client.get(reverse("contrato_terminais"))

        self.assertContains(response, "Inativo")
        self.assertNotContains(response, ">Ativo<")
        terminal.refresh_from_db()
        self.assertFalse(terminal.ativo)


class ValidacaoDocumentoTests(AssinaturaBaseTests):
    """Validação pública de PDF assinado — serviço e página.

    Herda de AssinaturaBaseTests para ter um contrato real com PDF em um
    MEDIA_ROOT temporário e as tarefas Celery mockadas.
    """

    def _assinar_contrato(self, contrato, validacao_url: str | None = None) -> bytes:
        """Assina um contrato e devolve os bytes do PDF assinado final."""

        sessao = criar_sessao(contrato, criado_por=self.usuario)
        _confirmar_identidade_sessao(sessao)
        processar_assinatura(
            sessao,
            _assinatura_data_url(),
            ip=None,
            user_agent="",
            validacao_url=validacao_url,
        )

        contrato.refresh_from_db()
        contrato.arquivo_pdf_assinado.open("rb")
        pdf = contrato.arquivo_pdf_assinado.read()
        contrato.arquivo_pdf_assinado.close()
        return pdf

    def _assinar(self) -> bytes:
        """Assina self.contrato e devolve os bytes do PDF assinado final."""

        return self._assinar_contrato(self.contrato)

    # ── Serviço ──────────────────────────────────────────────────────

    def test_hash_arquivo_assinado_gravado_na_assinatura(self) -> None:
        pdf = self._assinar()

        self.assertEqual(
            self.contrato.hash_arquivo_assinado,
            hashlib.sha256(pdf).hexdigest(),
        )

    def test_validar_pdf_autentico(self) -> None:
        pdf = self._assinar()

        resultado = validar_pdf(pdf)

        self.assertTrue(resultado.autentico)
        self.assertEqual(resultado.contrato, self.contrato)
        self.assertIsNotNone(resultado.sessao)
        self.assertEqual(resultado.hash_sha256, hashlib.sha256(pdf).hexdigest())

    def test_validar_pdf_adulterado_nao_confere(self) -> None:
        pdf = self._assinar()
        adulterado = pdf + b"%alteracao"

        resultado = validar_pdf(adulterado)

        self.assertFalse(resultado.autentico)
        self.assertIsNone(resultado.contrato)

    def test_validar_pdf_nao_emitido_nao_confere(self) -> None:
        resultado = validar_pdf(b"%PDF-1.4 documento qualquer nao emitido aqui")

        self.assertFalse(resultado.autentico)

    def test_validar_arquivo_vazio_levanta(self) -> None:
        with self.assertRaises(ArquivoInvalido):
            validar_pdf(b"")

    def test_validar_nao_pdf_levanta(self) -> None:
        with self.assertRaises(ArquivoInvalido):
            validar_pdf(b"isto nao e um PDF")

    # ── Página pública ───────────────────────────────────────────────

    def test_get_renderiza_formulario(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("validar_documento"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validar documento")

    def test_post_pdf_autentico_mostra_selo(self) -> None:
        pdf = self._assinar()
        self.client.logout()  # página é pública

        response = self.client.post(
            reverse("validar_documento"),
            {"documento": SimpleUploadedFile("assinado.pdf", pdf, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Documento autêntico")
        self.assertContains(response, self.pac.nome)

    def test_post_pdf_adulterado_mostra_falha(self) -> None:
        pdf = self._assinar()
        self.client.logout()

        response = self.client.post(
            reverse("validar_documento"),
            {
                "documento": SimpleUploadedFile(
                    "adulterado.pdf", pdf + b"x", "application/pdf"
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível validar")
        self.assertNotContains(response, self.pac.nome)

    def test_post_sem_arquivo_mostra_erro(self) -> None:
        self.client.logout()

        response = self.client.post(reverse("validar_documento"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um arquivo PDF")

    def test_url_validacao_impressa_no_rodape_do_pdf(self) -> None:
        from pypdf import PdfReader

        sessao = criar_sessao(self.contrato, criado_por=self.usuario)
        _confirmar_identidade_sessao(sessao)
        processar_assinatura(
            sessao,
            _assinatura_data_url(),
            ip=None,
            user_agent="",
            validacao_url="https://exemplo.test/contratos/validar/",
        )

        self.contrato.refresh_from_db()
        self.contrato.arquivo_pdf_assinado.open("rb")
        pdf = self.contrato.arquivo_pdf_assinado.read()
        self.contrato.arquivo_pdf_assinado.close()

        texto = "".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages
        )
        self.assertIn("validar", texto)

    def test_qr_de_validacao_adicionado_ao_rodape(self) -> None:
        from pypdf import PdfReader

        def imagens_ultima_pagina(pdf: bytes) -> int:
            return len(list(PdfReader(io.BytesIO(pdf)).pages[-1].images))

        pdf_sem = self._assinar_contrato(self.contrato, validacao_url=None)

        outro = gerar_e_salvar_contrato(
            paciente=_paciente_completo(id_dental="601"),
            tipo="modelo_1",
            gerado_por=self.usuario,
        )
        pdf_com = self._assinar_contrato(
            outro, validacao_url="https://exemplo.test/contratos/validar/"
        )

        # O PDF com URL de validação leva uma imagem a mais no rodapé (o QR
        # Code), além da assinatura desenhada presente em ambos.
        self.assertEqual(
            imagens_ultima_pagina(pdf_com), imagens_ultima_pagina(pdf_sem) + 1
        )
