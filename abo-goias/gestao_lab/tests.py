"""Testes da aplicação de gestão de laboratório.

Cobre models, views, formulários e integração com o Dental Office.
Prioridade: views e integração Dental (maior risco de quebra) → models →
formulários → permissões.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from gestao_lab.forms import (
    EquipeForm,
    LaboratorioForm,
    MoldagemForm,
    PedidoMaterialForm,
)
from gestao_lab.integrations.dental import (
    DentalAPIError,
    DentalClient,
    DentalConfigurationError,
    DentalConnectionError,
    DentalInvalidResponseError,
    DentalNotFoundError,
    DentalRateLimitError,
    DentalServerError,
    DentalTimeoutError,
    PacienteDental,
    carregar_config_dental,
)
from gestao_lab.models import (
    AlunoLab,
    Equipe,
    Laboratorio,
    Moldagem,
    OrigemDados,
    Paciente,
    PedidoMaterial,
    RegistroSync,
)
from gestao_lab.services.cobranca import cobrar_laboratorios_atrasados
from gestao_lab.services.dental_sync import (
    buscar_e_importar_alunos,
    buscar_e_importar_pacientes,
    listar_todas_paginas,
)
from gestao_lab.tasks import cobrar_pedidos_atrasados_task, sincronizar_dental_task
from mensageria import MessagingResult

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usuario(username: str = "coord", superuser: bool = False) -> User:
    return User.objects.create_user(
        username=username,
        password="senha-segura",
        is_superuser=superuser,
    )


def _paciente(**kwargs) -> Paciente:
    defaults = {"nome": "Paciente Teste", "id_dental": "100"}
    defaults.update(kwargs)
    return Paciente.objects.create(**defaults)


def _aluno(**kwargs) -> AlunoLab:
    defaults = {"nome": "Aluno Teste", "id_dental": "200"}
    defaults.update(kwargs)
    return AlunoLab.objects.create(**defaults)


def _equipe(**kwargs) -> Equipe:
    defaults = {"nome": "Equipe A", "coordenador": "Dr. Coord"}
    defaults.update(kwargs)
    return Equipe.objects.create(**defaults)


def _laboratorio(equipe: Equipe | None = None, **kwargs) -> Laboratorio:
    defaults = {"nome": "Lab Teste"}
    defaults.update(kwargs)
    lab = Laboratorio.objects.create(**defaults)
    if equipe:
        lab.equipes.add(equipe)
    return lab


def _pedido(
    paciente: Paciente, aluno: AlunoLab, lab: Laboratorio, equipe: Equipe, **kwargs
) -> PedidoMaterial:
    defaults = {
        "previsao_entrega": date.today() + timedelta(days=7),
        "descricao_servico": "Prótese total",
    }
    defaults.update(kwargs)
    return PedidoMaterial.objects.create(
        paciente=paciente,
        aluno=aluno,
        laboratorio=lab,
        equipe=equipe,
        **defaults,
    )


# ---------------------------------------------------------------------------
# Testes de Models
# ---------------------------------------------------------------------------


class EquipeModelTests(TestCase):
    def test_str_retorna_nome(self) -> None:
        equipe = Equipe.objects.create(nome="Equipe Alpha", coordenador="Dr. Alpha")
        self.assertEqual(str(equipe), "Equipe Alpha")

    def test_defaults_ativo_e_auditoria(self) -> None:
        equipe = Equipe.objects.create(nome="Equipe Beta", coordenador="Dr. Beta")
        self.assertTrue(equipe.ativo)
        self.assertIsNotNone(equipe.criado_em)
        self.assertIsNotNone(equipe.atualizado_em)

    def test_whatsapp_opcional(self) -> None:
        equipe = Equipe.objects.create(nome="Equipe Gama", coordenador="Dr. Gama")
        self.assertEqual(equipe.whatsapp, "")


class LaboratorioModelTests(TestCase):
    def test_str_retorna_nome(self) -> None:
        lab = Laboratorio.objects.create(nome="Lab Dental")
        self.assertEqual(str(lab), "Lab Dental")

    def test_vincula_multiplas_equipes(self) -> None:
        lab = Laboratorio.objects.create(nome="Lab Multi")
        eq1 = Equipe.objects.create(nome="Eq 1", coordenador="Coord 1")
        eq2 = Equipe.objects.create(nome="Eq 2", coordenador="Coord 2")
        lab.equipes.add(eq1, eq2)
        self.assertEqual(lab.equipes.count(), 2)

    def test_campos_opcionais_em_branco(self) -> None:
        lab = Laboratorio.objects.create(nome="Lab Simples")
        self.assertEqual(lab.telefone, "")
        self.assertEqual(lab.cnpj, "")
        self.assertEqual(lab.email, "")


class AlunoLabModelTests(TestCase):
    def test_str_retorna_nome(self) -> None:
        aluno = AlunoLab.objects.create(nome="Ana Clara", id_dental="500")
        self.assertEqual(str(aluno), "Ana Clara")

    def test_id_dental_deve_ser_unico(self) -> None:
        AlunoLab.objects.create(nome="Aluno 1", id_dental="duplicado")
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            AlunoLab.objects.create(nome="Aluno 2", id_dental="duplicado")

    def test_origem_default_dental(self) -> None:
        aluno = AlunoLab.objects.create(nome="Aluno Origem", id_dental="600")
        self.assertEqual(aluno.origem, OrigemDados.DENTAL)


class PacienteModelTests(TestCase):
    def test_str_retorna_nome(self) -> None:
        pac = _paciente(nome="Maria Silva")
        self.assertEqual(str(pac), "Maria Silva")

    def test_dados_contrato_completos_com_cpf_e_cidade(self) -> None:
        pac = _paciente(
            id_dental="101",
            cpf="123.456.789-00",
            endereco_cidade="Goiânia",
        )
        self.assertTrue(pac.dados_contrato_completos)

    def test_dados_contrato_completos_com_rg_e_cidade(self) -> None:
        pac = _paciente(id_dental="102", rg="1234567", endereco_cidade="Goiânia")
        self.assertTrue(pac.dados_contrato_completos)

    def test_dados_contrato_incompletos_sem_documento(self) -> None:
        pac = _paciente(id_dental="103", endereco_cidade="Goiânia")
        self.assertFalse(pac.dados_contrato_completos)

    def test_dados_contrato_incompletos_sem_cidade(self) -> None:
        pac = _paciente(id_dental="104", cpf="111.222.333-44")
        self.assertFalse(pac.dados_contrato_completos)

    def test_dados_contrato_incompletos_sem_nada(self) -> None:
        pac = _paciente(id_dental="105")
        self.assertFalse(pac.dados_contrato_completos)

    def test_id_dental_unico(self) -> None:
        _paciente(id_dental="dup")
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            _paciente(id_dental="dup")


class PedidoMaterialStatusTests(TestCase):
    def setUp(self) -> None:
        self.pac = _paciente(id_dental="10")
        self.aluno = _aluno(id_dental="20")
        self.equipe = _equipe()
        self.lab = _laboratorio(equipe=self.equipe)

    def test_status_em_dia_quando_novo_e_dentro_do_prazo(self) -> None:
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.EM_DIA)

    def test_status_atrasado_quando_prazo_vencido_sem_entrega(self) -> None:
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=1),
            entregue=False,
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.ATRASADO)

    def test_status_em_dia_quando_enviado_mas_nao_entregue_dentro_do_prazo(
        self,
    ) -> None:
        # "Enviado, aguardando devolução, dentro do prazo" nao e mais uma
        # categoria propria de status (era A_CONFIRMAR) — conta como "Em dia",
        # que cobre qualquer pedido nao entregue dentro do prazo.
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
            data_envio=date.today(),
            entregue=False,
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.EM_DIA)

    def test_status_concluido_quando_entregue_e_faturado(self) -> None:
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
            entregue=True,
            faturado_paciente=True,
            faturado_lab=True,
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.CONCLUIDO)

    def test_status_entregue_nao_faturado_quando_faturamento_incompleto(
        self,
    ) -> None:
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
            entregue=True,
            faturado_paciente=True,
            faturado_lab=False,
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.ENTREGUE_NAO_FATURADO)

    def test_status_entregue_nao_faturado_mesmo_com_prazo_vencido(self) -> None:
        # Um pedido entregue nunca deve ser classificado como ATRASADO, mesmo
        # que a entrega tenha acontecido depois do prazo — "atrasado" so se
        # aplica a pedidos ainda nao entregues.
        pedido = _pedido(
            self.pac,
            self.aluno,
            self.lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
            entregue=True,
            faturado_paciente=False,
            faturado_lab=False,
        )
        self.assertEqual(pedido.status, PedidoMaterial.Status.ENTREGUE_NAO_FATURADO)

    def test_str_inclui_numero_paciente_e_lab(self) -> None:
        pedido = _pedido(self.pac, self.aluno, self.lab, self.equipe)
        texto = str(pedido)
        self.assertIn("Pedido #", texto)
        self.assertIn("Paciente Teste", texto)
        self.assertIn("Lab Teste", texto)


class MoldagemModelTests(TestCase):
    def setUp(self) -> None:
        self.pac = _paciente(id_dental="30")
        self.aluno = _aluno(id_dental="40")

    def test_str_inclui_numero_paciente_e_aluno(self) -> None:
        moldagem = Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)
        self.assertIn("Moldagem #", str(moldagem))
        self.assertIn("Paciente Teste", str(moldagem))

    def test_convertida_false_sem_pedido_vinculado(self) -> None:
        moldagem = Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)
        self.assertFalse(moldagem.convertida)

    def test_convertida_true_com_pedido_vinculado(self) -> None:
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        pedido = _pedido(self.pac, self.aluno, lab, equipe)
        moldagem = Moldagem.objects.create(
            paciente=self.pac, aluno=self.aluno, pedido_material=pedido
        )
        self.assertTrue(moldagem.convertida)


class RegistroSyncModelTests(TestCase):
    def test_str_com_sucesso(self) -> None:
        sync = RegistroSync.objects.create(sucesso=True)
        self.assertIn("OK", str(sync))

    def test_str_com_erro(self) -> None:
        sync = RegistroSync.objects.create(sucesso=False, erro="timeout")
        self.assertIn("ERRO", str(sync))


# ---------------------------------------------------------------------------
# Testes de Views — autenticação
# ---------------------------------------------------------------------------


class AutenticacaoLabTests(TestCase):
    """Garante que todas as views exigem login."""

    def _assert_redireciona(self, url_name: str, **kwargs) -> None:
        url = reverse(url_name, **kwargs)
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f'{reverse("login")}?next={url}',
            fetch_redirect_response=False,
        )

    def test_dashboard_exige_login(self) -> None:
        self._assert_redireciona("lab_dashboard")

    def test_pedidos_exige_login(self) -> None:
        self._assert_redireciona("lab_pedidos")

    def test_moldagens_exige_login(self) -> None:
        self._assert_redireciona("lab_moldagens")

    def test_laboratorios_exige_login(self) -> None:
        self._assert_redireciona("lab_laboratorios")

    def test_equipes_exige_login(self) -> None:
        self._assert_redireciona("lab_equipes")

    def test_alunos_exige_login(self) -> None:
        self._assert_redireciona("lab_alunos")

    def test_pacientes_exige_login(self) -> None:
        self._assert_redireciona("lab_pacientes")


# ---------------------------------------------------------------------------
# Testes de Views — dashboard
# ---------------------------------------------------------------------------


class DashboardLabTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/dashboard.html")

    def test_metricas_contam_pedidos_por_status(self) -> None:
        pac = _paciente(id_dental="11")
        aluno = _aluno(id_dental="21")
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        _pedido(
            pac, aluno, lab, equipe, previsao_entrega=date.today() + timedelta(days=3)
        )
        _pedido(
            pac,
            aluno,
            lab,
            equipe,
            previsao_entrega=date.today() - timedelta(days=1),
            entregue=False,
        )

        response = self.client.get(reverse("lab_dashboard"))

        metricas = response.context["metricas"]
        self.assertEqual(metricas["em_dia"], 1)
        self.assertEqual(metricas["atrasado"], 1)

    def test_metricas_contam_entregue_nao_faturado_e_concluidos(self) -> None:
        pac = _paciente(id_dental="13")
        aluno = _aluno(id_dental="23")
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        _pedido(
            pac,
            aluno,
            lab,
            equipe,
            previsao_entrega=date.today() + timedelta(days=3),
            entregue=True,
            faturado_paciente=True,
            faturado_lab=False,
        )
        _pedido(
            pac,
            aluno,
            lab,
            equipe,
            previsao_entrega=date.today() + timedelta(days=3),
            entregue=True,
            faturado_paciente=True,
            faturado_lab=True,
        )

        response = self.client.get(reverse("lab_dashboard"))

        metricas = response.context["metricas"]
        self.assertEqual(metricas["entregue_nao_faturado"], 1)
        self.assertEqual(metricas["concluidos"], 1)


# ---------------------------------------------------------------------------
# Testes de Views — acompanhamento de pedidos
# ---------------------------------------------------------------------------


class AcompanhamentoPedidosTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)
        pac = _paciente(id_dental="12")
        aluno = _aluno(id_dental="22")
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        self.pedido_em_dia = _pedido(
            pac,
            aluno,
            lab,
            equipe,
            previsao_entrega=date.today() + timedelta(days=5),
        )
        self.pedido_atrasado = _pedido(
            pac,
            aluno,
            lab,
            equipe,
            previsao_entrega=date.today() - timedelta(days=2),
            entregue=False,
        )

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_pedidos"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/acompanhamento_pedidos.html")

    def test_filtra_por_status_atrasado(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos"), {"status": PedidoMaterial.Status.ATRASADO}
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.pedido_atrasado, pedidos)
        self.assertNotIn(self.pedido_em_dia, pedidos)

    def test_filtra_por_status_em_dia(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos"), {"status": PedidoMaterial.Status.EM_DIA}
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.pedido_em_dia, pedidos)
        self.assertNotIn(self.pedido_atrasado, pedidos)

    def test_busca_por_nome_do_paciente(self) -> None:
        response = self.client.get(reverse("lab_pedidos"), {"q": "Paciente Teste"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paciente Teste")

    def test_filtra_por_status_entregue_nao_faturado(self) -> None:
        pedido_entregue = _pedido(
            self.pedido_em_dia.paciente,
            self.pedido_em_dia.aluno,
            self.pedido_em_dia.laboratorio,
            self.pedido_em_dia.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
            entregue=True,
            faturado_paciente=False,
            faturado_lab=False,
        )

        response = self.client.get(
            reverse("lab_pedidos"),
            {"status": PedidoMaterial.Status.ENTREGUE_NAO_FATURADO},
        )

        pedidos = list(response.context["pedidos"])
        self.assertIn(pedido_entregue, pedidos)
        self.assertNotIn(self.pedido_em_dia, pedidos)
        self.assertNotIn(self.pedido_atrasado, pedidos)


# ---------------------------------------------------------------------------
# Testes de Views — fila de faturamento
# ---------------------------------------------------------------------------


class PedidosFaturamentoViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)
        pac = _paciente(id_dental="14")
        aluno = _aluno(id_dental="24")
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        self.pendente_dos_dois_lados = _pedido(
            pac,
            aluno,
            lab,
            equipe,
            entregue=True,
            faturado_paciente=False,
            faturado_lab=False,
        )
        self.faturado_so_paciente = _pedido(
            pac,
            aluno,
            lab,
            equipe,
            entregue=True,
            faturado_paciente=True,
            faturado_lab=False,
        )
        self.faturado_so_lab = _pedido(
            pac,
            aluno,
            lab,
            equipe,
            entregue=True,
            faturado_paciente=False,
            faturado_lab=True,
        )

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_pedidos_faturamento"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/pedidos_faturamento.html")

    def test_lista_todos_os_pendentes_sem_filtro(self) -> None:
        response = self.client.get(reverse("lab_pedidos_faturamento"))
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.pendente_dos_dois_lados, pedidos)
        self.assertIn(self.faturado_so_paciente, pedidos)
        self.assertIn(self.faturado_so_lab, pedidos)

    def test_filtra_por_faturado_paciente_sim(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos_faturamento"), {"faturado_paciente": "sim"}
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.faturado_so_paciente, pedidos)
        self.assertNotIn(self.pendente_dos_dois_lados, pedidos)
        self.assertNotIn(self.faturado_so_lab, pedidos)

    def test_filtra_por_faturado_paciente_nao(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos_faturamento"), {"faturado_paciente": "nao"}
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.pendente_dos_dois_lados, pedidos)
        self.assertIn(self.faturado_so_lab, pedidos)
        self.assertNotIn(self.faturado_so_paciente, pedidos)

    def test_filtra_por_faturado_lab_sim(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos_faturamento"), {"faturado_lab": "sim"}
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.faturado_so_lab, pedidos)
        self.assertNotIn(self.pendente_dos_dois_lados, pedidos)
        self.assertNotIn(self.faturado_so_paciente, pedidos)

    def test_combina_os_dois_filtros(self) -> None:
        response = self.client.get(
            reverse("lab_pedidos_faturamento"),
            {"faturado_paciente": "nao", "faturado_lab": "nao"},
        )
        pedidos = list(response.context["pedidos"])
        self.assertIn(self.pendente_dos_dois_lados, pedidos)
        self.assertNotIn(self.faturado_so_paciente, pedidos)
        self.assertNotIn(self.faturado_so_lab, pedidos)


# ---------------------------------------------------------------------------
# Testes de Views — moldagens
# ---------------------------------------------------------------------------


class MoldagensViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)
        self.pac = _paciente(id_dental="13")
        self.aluno = _aluno(id_dental="23")

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_moldagens"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/moldagens.html")

    def test_lista_moldagens_existentes(self) -> None:
        Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)
        response = self.client.get(reverse("lab_moldagens"))
        self.assertContains(response, "Paciente Teste")

    def test_filtra_por_convertidas(self) -> None:
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        pedido = _pedido(self.pac, self.aluno, lab, equipe)
        moldagem_convertida = Moldagem.objects.create(
            paciente=self.pac, aluno=self.aluno, pedido_material=pedido
        )
        moldagem_simples = Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)

        response = self.client.get(reverse("lab_moldagens"), {"filtro": "convertida"})
        ids = [m.pk for m in response.context["moldagens"]]
        self.assertIn(moldagem_convertida.pk, ids)
        self.assertNotIn(moldagem_simples.pk, ids)


# ---------------------------------------------------------------------------
# Testes de Views — laboratórios e equipes
# ---------------------------------------------------------------------------


class LaboratoriosViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_laboratorios"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/laboratorios.html")

    def test_lista_laboratorios_existentes(self) -> None:
        Laboratorio.objects.create(nome="Lab Odonto")
        response = self.client.get(reverse("lab_laboratorios"))
        self.assertContains(response, "Lab Odonto")

    def test_busca_filtra_por_nome(self) -> None:
        Laboratorio.objects.create(nome="Lab Goias")
        Laboratorio.objects.create(nome="Lab Nacional")
        response = self.client.get(reverse("lab_laboratorios"), {"q": "Goias"})
        self.assertContains(response, "Lab Goias")
        self.assertNotContains(response, "Lab Nacional")

    def test_criar_laboratorio_get_200(self) -> None:
        response = self.client.get(reverse("lab_criar_laboratorio"))
        self.assertEqual(response.status_code, 200)

    def test_criar_laboratorio_post_valido_redireciona(self) -> None:
        response = self.client.post(
            reverse("lab_criar_laboratorio"),
            {"nome": "Lab Novo"},
        )
        self.assertRedirects(
            response, reverse("lab_laboratorios"), fetch_redirect_response=False
        )
        self.assertTrue(Laboratorio.objects.filter(nome="Lab Novo").exists())


class EquipesViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_equipes"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/equipes.html")

    def test_lista_equipes_existentes(self) -> None:
        Equipe.objects.create(nome="Equipe Goiania", coordenador="Dr. A")
        response = self.client.get(reverse("lab_equipes"))
        self.assertContains(response, "Equipe Goiania")

    def test_criar_equipe_post_valido_redireciona(self) -> None:
        response = self.client.post(
            reverse("lab_criar_equipe"),
            {"nome": "Equipe Nova", "coordenador": "Dr. Novo"},
        )
        self.assertRedirects(
            response, reverse("lab_equipes"), fetch_redirect_response=False
        )
        self.assertTrue(Equipe.objects.filter(nome="Equipe Nova").exists())

    def test_criar_equipe_post_invalido_exibe_erro(self) -> None:
        response = self.client.post(reverse("lab_criar_equipe"), {"nome": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe o nome da equipe")


# ---------------------------------------------------------------------------
# Testes de Views — pacientes e alunos
# ---------------------------------------------------------------------------


class PacientesViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_pacientes"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/pacientes.html")

    def test_lista_pacientes_ativos(self) -> None:
        _paciente(nome="Joao Ativo", id_dental="300")
        _paciente(nome="Maria Inativa", id_dental="301", ativo=False)
        response = self.client.get(reverse("lab_pacientes"))
        self.assertContains(response, "Joao Ativo")
        self.assertNotContains(response, "Maria Inativa")

    def test_filtra_pacientes_com_pedido_aberto(self) -> None:
        # "Pedido em aberto" passou a significar ter um PedidoMaterial não
        # concluído (antes era o flag processo_aberto vindo do Dental Office).
        com = _paciente(nome="Com Pedido", id_dental="302")
        sem = _paciente(nome="Sem Pedido", id_dental="303")
        aluno = _aluno()
        equipe = _equipe()
        lab = _laboratorio()
        # 'com' tem um pedido em aberto; 'sem' tem só um pedido já concluído.
        _pedido(com, aluno, lab, equipe)
        _pedido(
            sem,
            aluno,
            lab,
            equipe,
            entregue=True,
            data_entrega=date.today(),
            faturado_paciente=True,
            faturado_lab=True,
        )
        response = self.client.get(reverse("lab_pacientes"), {"pedido": "aberto"})
        self.assertContains(response, "Com Pedido")
        self.assertNotContains(response, "Sem Pedido")


class AlunosLabViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    def test_retorna_200_e_template_correto(self) -> None:
        response = self.client.get(reverse("lab_alunos"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "gestao_lab/alunos.html")

    def test_lista_alunos_ativos(self) -> None:
        AlunoLab.objects.create(nome="Aluno Ativo", id_dental="400")
        AlunoLab.objects.create(nome="Aluno Inativo", id_dental="401", ativo=False)
        response = self.client.get(reverse("lab_alunos"))
        self.assertContains(response, "Aluno Ativo")
        self.assertNotContains(response, "Aluno Inativo")


# ---------------------------------------------------------------------------
# Testes de integração — Dental Office (views com mock)
# ---------------------------------------------------------------------------


class SincronizarDentalViewTests(TestCase):
    def setUp(self) -> None:
        self.usuario = _usuario()
        self.client.force_login(self.usuario)

    @override_settings(DENTAL_CLINIC_ID="clinic-test", DENTAL_USER_GROUP_ALUNO=8)
    @patch("gestao_lab.services.dental_sync.executar_sync_e_registrar")
    def test_sincronizacao_bem_sucedida_exibe_mensagem(
        self, mock_sync: MagicMock
    ) -> None:
        mock_sync.return_value = MagicMock(
            duracao_segundos=1.2,
            pacientes_criados=3,
            pacientes_atualizados=1,
            alunos_criados=2,
            alunos_atualizados=0,
        )

        response = self.client.post(reverse("lab_sincronizar"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sincronização concluída")

    @override_settings(DENTAL_CLINIC_ID="clinic-test", DENTAL_USER_GROUP_ALUNO=8)
    @patch("gestao_lab.services.dental_sync.executar_sync_e_registrar")
    def test_sincronizacao_com_erro_api_exibe_mensagem_erro(
        self, mock_sync: MagicMock
    ) -> None:
        mock_sync.side_effect = DentalAPIError("serviço indisponível")

        response = self.client.post(reverse("lab_sincronizar"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "serviço indisponível")

    @override_settings(DENTAL_CLINIC_ID=None)
    def test_sincronizacao_sem_clinic_id_exibe_erro(self) -> None:
        response = self.client.post(reverse("lab_sincronizar"), follow=True)

        self.assertEqual(response.status_code, 200)
        # A mensagem e para o operador: diz o que fazer, sem citar a variavel de
        # ambiente nem o sistema de origem.
        self.assertContains(response, "não está configurada")
        self.assertContains(response, "suporte técnico")

    @override_settings(DENTAL_CLINIC_ID="clinic-test")
    @patch("gestao_lab.services.dental_sync.buscar_e_importar_pacientes")
    def test_busca_paciente_dental_importa_e_exibe_mensagem(
        self, mock_buscar: MagicMock
    ) -> None:
        mock_buscar.return_value = {"criados": 1, "atualizados": 0}

        response = self.client.get(
            reverse("lab_buscar_paciente"),
            {"q": "Carlos", "next": "lab_criar_pedido"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "importado")

    @override_settings(DENTAL_CLINIC_ID="clinic-test")
    @patch("gestao_lab.services.dental_sync.buscar_e_importar_pacientes")
    def test_busca_paciente_dental_sem_resultado_exibe_aviso(
        self, mock_buscar: MagicMock
    ) -> None:
        mock_buscar.return_value = {"criados": 0, "atualizados": 0}

        response = self.client.get(
            reverse("lab_buscar_paciente"),
            {"q": "Inexistente", "next": "lab_criar_pedido"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum paciente encontrado")


# ---------------------------------------------------------------------------
# Testes de Formulários
# ---------------------------------------------------------------------------


class PedidoMaterialFormTests(TestCase):
    def setUp(self) -> None:
        self.pac = _paciente(id_dental="50")
        self.aluno = _aluno(id_dental="60")
        self.equipe = _equipe()
        self.lab = _laboratorio(equipe=self.equipe)

    def _dados_validos(self) -> dict:
        return {
            "paciente": self.pac.pk,
            "aluno": self.aluno.pk,
            "laboratorio": self.lab.pk,
            "equipe": self.equipe.pk,
            "previsao_entrega": (date.today() + timedelta(days=10)).strftime(
                "%Y-%m-%d"
            ),
            "descricao_servico": "Prótese parcial removível",
        }

    def test_form_valido_com_dados_corretos(self) -> None:
        form = PedidoMaterialForm(data=self._dados_validos())
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalido_sem_paciente(self) -> None:
        dados = self._dados_validos()
        dados.pop("paciente")
        form = PedidoMaterialForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn("paciente", form.errors)

    def test_form_invalido_sem_descricao(self) -> None:
        dados = self._dados_validos()
        dados["descricao_servico"] = ""
        form = PedidoMaterialForm(data=dados)
        self.assertFalse(form.is_valid())
        self.assertIn("descricao_servico", form.errors)

    def test_mensagem_erro_paciente_obrigatorio(self) -> None:
        form = PedidoMaterialForm(data={})
        self.assertIn("Selecione o paciente", str(form.errors.get("paciente", "")))


class MoldagemFormTests(TestCase):
    def test_form_valido(self) -> None:
        pac = _paciente(id_dental="70")
        aluno = _aluno(id_dental="80")
        form = MoldagemForm(data={"paciente": pac.pk, "aluno": aluno.pk})
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalido_sem_aluno(self) -> None:
        pac = _paciente(id_dental="71")
        form = MoldagemForm(data={"paciente": pac.pk})
        self.assertFalse(form.is_valid())
        self.assertIn("aluno", form.errors)

    def test_mensagem_erro_aluno_obrigatorio(self) -> None:
        form = MoldagemForm(data={})
        self.assertIn("Selecione o aluno", str(form.errors.get("aluno", "")))


class EquipeFormTests(TestCase):
    def test_form_valido(self) -> None:
        form = EquipeForm(data={"nome": "Eq X", "coordenador": "Dr. X"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalido_sem_nome(self) -> None:
        form = EquipeForm(data={"coordenador": "Dr. Y"})
        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)

    def test_mensagem_erro_nome_obrigatorio(self) -> None:
        form = EquipeForm(data={})
        self.assertIn("Informe o nome da equipe", str(form.errors.get("nome", "")))


class LaboratorioFormTests(TestCase):
    def test_form_valido_apenas_com_nome(self) -> None:
        form = LaboratorioForm(data={"nome": "Lab Z"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalido_sem_nome(self) -> None:
        form = LaboratorioForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)

    def test_mensagem_erro_nome_obrigatorio(self) -> None:
        form = LaboratorioForm(data={})
        self.assertIn("Informe o nome do laboratório", str(form.errors.get("nome", "")))


# ---------------------------------------------------------------------------
# Cobrança automática de pedidos atrasados (WhatsApp)
# ---------------------------------------------------------------------------


class CobrarLaboratoriosAtrasadosTests(TestCase):
    def setUp(self) -> None:
        self.pac = _paciente(id_dental="10")
        self.aluno = _aluno(id_dental="20")
        self.equipe = _equipe()

    def test_sem_mensageria_configurada_nao_faz_nada(self) -> None:
        with patch(
            "gestao_lab.services.cobranca.messaging_configurado", return_value=False
        ):
            total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 0)

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_agrega_pedidos_do_mesmo_laboratorio_numa_unica_mensagem(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_texto.return_value = MessagingResult.ok(
            "id-1"
        )
        lab = _laboratorio(equipe=self.equipe, whatsapp="62999998888")
        pedido1 = _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
        )
        pedido2 = _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=1),
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 1)
        mock_get_service.return_value.enviar_texto.assert_called_once()
        destinatario, mensagem = mock_get_service.return_value.enviar_texto.call_args[0]
        self.assertEqual(destinatario, "5562999998888")
        self.assertIn(f"Pedido #{pedido1.pk}", mensagem)
        self.assertIn(f"Pedido #{pedido2.pk}", mensagem)
        pedido1.refresh_from_db()
        pedido2.refresh_from_db()
        self.assertIsNotNone(pedido1.cobranca_whatsapp_enviada_em)
        self.assertIsNotNone(pedido2.cobranca_whatsapp_enviada_em)

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_pedido_ja_cobrado_hoje_nao_e_cobrado_de_novo(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_texto.return_value = MessagingResult.ok(
            "id-1"
        )
        lab = _laboratorio(equipe=self.equipe, whatsapp="62999998888")
        _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
        )

        primeira_execucao = cobrar_laboratorios_atrasados()
        segunda_execucao = cobrar_laboratorios_atrasados()

        self.assertEqual(primeira_execucao, 1)
        self.assertEqual(segunda_execucao, 0)
        mock_get_service.return_value.enviar_texto.assert_called_once()

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_pedido_cobrado_ontem_e_cobrado_novamente_hoje(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_texto.return_value = MessagingResult.ok(
            "id-1"
        )
        lab = _laboratorio(equipe=self.equipe, whatsapp="62999998888")
        pedido = _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
        )
        PedidoMaterial.objects.filter(pk=pedido.pk).update(
            cobranca_whatsapp_enviada_em=timezone.now() - timedelta(days=1)
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 1)

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_laboratorio_sem_whatsapp_e_ignorado(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        lab = _laboratorio(equipe=self.equipe, whatsapp="")
        _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 0)
        mock_get_service.return_value.enviar_texto.assert_not_called()

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_pedido_em_dia_nao_e_cobrado(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        lab = _laboratorio(equipe=self.equipe, whatsapp="62999998888")
        _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() + timedelta(days=5),
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 0)
        mock_get_service.return_value.enviar_texto.assert_not_called()

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_falha_no_envio_nao_marca_pedido_como_cobrado(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_texto.return_value = MessagingResult.falha(
            "instância desconectada"
        )
        lab = _laboratorio(equipe=self.equipe, whatsapp="62999998888")
        pedido = _pedido(
            self.pac,
            self.aluno,
            lab,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=3),
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 0)
        pedido.refresh_from_db()
        self.assertIsNone(pedido.cobranca_whatsapp_enviada_em)

    @patch("gestao_lab.services.cobranca.get_messaging_service")
    @patch("gestao_lab.services.cobranca.messaging_configurado", return_value=True)
    def test_dois_laboratorios_geram_duas_mensagens_separadas(
        self, mock_configurado: MagicMock, mock_get_service: MagicMock
    ) -> None:
        mock_get_service.return_value.enviar_texto.return_value = MessagingResult.ok(
            "id-1"
        )
        lab1 = _laboratorio(equipe=self.equipe, nome="Lab 1", whatsapp="62999998888")
        lab2 = _laboratorio(equipe=self.equipe, nome="Lab 2", whatsapp="62999997777")
        _pedido(
            self.pac,
            self.aluno,
            lab1,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=2),
        )
        _pedido(
            self.pac,
            self.aluno,
            lab2,
            self.equipe,
            previsao_entrega=date.today() - timedelta(days=2),
        )

        total = cobrar_laboratorios_atrasados()

        self.assertEqual(total, 2)
        self.assertEqual(mock_get_service.return_value.enviar_texto.call_count, 2)


class CobrarPedidosAtrasadosTaskTests(TestCase):
    @patch("gestao_lab.services.cobranca.cobrar_laboratorios_atrasados")
    def test_chama_o_service_e_retorna_o_total(self, mock_cobrar: MagicMock) -> None:
        mock_cobrar.return_value = 2

        resultado = cobrar_pedidos_atrasados_task.delay()

        self.assertEqual(resultado.get(), 2)
        mock_cobrar.assert_called_once()


# ---------------------------------------------------------------------------
# Paginação da API Dental Office
# ---------------------------------------------------------------------------


class ListarTodasPaginasTests(TestCase):
    """Testa o consolidador de páginas isoladamente, sem HTTP — a comunicação
    em si é coberta por DentalClientHttpTests."""

    def test_pagina_unica_com_poucos_registros(self) -> None:
        buscar = MagicMock(
            return_value={"results": [{"id": 1}, {"id": 2}], "total_pages": 1}
        )

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual(len(itens), 2)
        buscar.assert_called_once_with(1)

    def test_resposta_vazia(self) -> None:
        buscar = MagicMock(return_value={"results": [], "total_pages": 1})

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual(itens, [])
        buscar.assert_called_once()

    def test_sem_total_pages_assume_pagina_unica(self) -> None:
        buscar = MagicMock(return_value={"results": [{"id": 1}]})

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual(len(itens), 1)
        buscar.assert_called_once()

    def test_preserva_ordenacao_original_entre_paginas(self) -> None:
        pagina1 = {"results": [{"id": i} for i in range(1, 61)], "total_pages": 2}
        pagina2 = {"results": [{"id": 61}], "total_pages": 2}
        buscar = MagicMock(side_effect=[pagina1, pagina2])

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual([item["id"] for item in itens], list(range(1, 62)))
        self.assertEqual(buscar.call_count, 2)

    def test_elimina_registros_duplicados_entre_paginas(self) -> None:
        pagina1 = {"results": [{"id": 1}, {"id": 2}], "total_pages": 2}
        pagina2 = {"results": [{"id": 2}, {"id": 3}], "total_pages": 2}
        buscar = MagicMock(side_effect=[pagina1, pagina2])

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual([item["id"] for item in itens], [1, 2, 3])

    def test_pagina_vazia_no_meio_interrompe_com_seguranca(self) -> None:
        pagina1 = {"results": [{"id": 1}], "total_pages": 3}
        pagina2 = {"results": [], "total_pages": 3}
        buscar = MagicMock(side_effect=[pagina1, pagina2])

        itens = listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual(len(itens), 1)
        self.assertEqual(buscar.call_count, 2)

    def test_falha_durante_paginacao_propaga_sem_engolir_erro(self) -> None:
        buscar = MagicMock(
            side_effect=[
                {"results": [{"id": 1}], "total_pages": 3},
                DentalAPIError("conexão perdida"),
            ]
        )

        with self.assertRaises(DentalAPIError):
            listar_todas_paginas(buscar, contexto="teste")

        self.assertEqual(buscar.call_count, 2)

    def test_max_paginas_evita_loop_infinito(self) -> None:
        # Cada página retorna um id diferente (como numa API real) para que
        # a deduplicação não interfira na contagem — o objetivo aqui é
        # provar que o loop para em max_paginas mesmo com total_pages=999.
        buscar = MagicMock(
            side_effect=lambda page: {"results": [{"id": page}], "total_pages": 999}
        )

        itens = listar_todas_paginas(buscar, contexto="teste", max_paginas=3)

        self.assertEqual(buscar.call_count, 3)
        self.assertEqual(len(itens), 3)

    def test_consistente_para_varias_quantidades_de_registros(self) -> None:
        """Mesmo mecanismo de paginação, independente da quantidade de páginas —
        cobre os cenários citados: 20, 60, 61, 130 e 500 registros."""

        tamanho_pagina = 60
        for total_registros in (20, 60, 61, 130, 500):
            with self.subTest(total=total_registros):
                ids = list(range(1, total_registros + 1))
                total_pages = max(1, -(-total_registros // tamanho_pagina))
                paginas = [
                    {
                        "results": [
                            {"id": i}
                            for i in ids[p * tamanho_pagina : (p + 1) * tamanho_pagina]
                        ],
                        "total_pages": total_pages,
                    }
                    for p in range(total_pages)
                ]
                buscar = MagicMock(side_effect=paginas)

                itens = listar_todas_paginas(buscar, contexto="teste")

                self.assertEqual(len(itens), total_registros)
                self.assertEqual(buscar.call_count, total_pages)


def _fake_response(corpo: dict, status: int = 200) -> MagicMock:
    """Simula a resposta de urlopen() no cliente Dental Office.

    Diferente do padrão usado no cliente da Z-API (``with urlopen(...) as
    response:``), ``DentalClient._executar_request`` faz
    ``response = urlopen(...)`` e depois ``with response: response.read()``
    — sem ``as`` —, então ``.read``/``.status`` precisam estar no mock de
    nível superior (a mesma referência), não em ``__enter__.return_value``.
    """
    cm = MagicMock()
    cm.read.return_value = json.dumps(corpo).encode("utf-8")
    cm.status = status
    cm.__enter__.return_value = cm
    return cm


def _fake_http_error(status: int, corpo: str = "{}") -> HTTPError:
    fp = io.BytesIO(corpo.encode("utf-8"))
    return HTTPError(
        url="https://dental.example/teste", code=status, msg="erro", hdrs=None, fp=fp
    )


class DentalClientHttpTests(TestCase):
    """DENTAL_USE_PROXY=True roteia as chamadas por urlopen() diretamente,
    o que é mais simples de mockar do que o caminho via build_opener()."""

    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)

    def _config(self, **kwargs):
        valores = {
            "DENTAL_CLIENT_ID": "cid",
            "DENTAL_SECRET": "sec",
            "DENTAL_USE_PROXY": True,
            "DENTAL_RETRY_BACKOFF_SECONDS": 0,
            **kwargs,
        }
        with override_settings(**valores):
            return carregar_config_dental()

    def test_sem_config_levanta_configuration_error(self) -> None:
        with override_settings(DENTAL_CLIENT_ID="", DENTAL_SECRET=""):
            with self.assertRaises(DentalConfigurationError):
                carregar_config_dental()

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_get_autenticado_com_sucesso(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_response({"results": [], "total_pages": 1}),
        ]
        client = DentalClient(self._config())

        resposta = client.listar_pacientes(clinic_id=1)

        self.assertEqual(resposta["total_pages"], 1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_401_renova_token_e_repete_uma_vez(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_http_error(401, '{"error": "expirado"}'),
            _fake_response({"token": "tok-2"}),
            _fake_response({"results": []}),
        ]
        client = DentalClient(self._config())

        resposta = client.listar_pacientes(clinic_id=1)

        self.assertEqual(resposta, {"results": []})
        self.assertEqual(mock_urlopen.call_count, 4)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_404_levanta_not_found(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_http_error(404, '{"error": "nao encontrado"}'),
        ]
        client = DentalClient(self._config())

        with self.assertRaises(DentalNotFoundError):
            client.listar_pacientes(clinic_id=1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_429_esgota_tentativas_e_levanta_rate_limit(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_http_error(429, '{"error": "limite"}'),
            _fake_http_error(429, '{"error": "limite"}'),
            _fake_http_error(429, '{"error": "limite"}'),
        ]
        client = DentalClient(self._config(DENTAL_MAX_RETRIES=3))

        with self.assertRaises(DentalRateLimitError):
            client.listar_pacientes(clinic_id=1)

        # 1 chamada de autenticação + 3 tentativas de GET
        self.assertEqual(mock_urlopen.call_count, 4)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_500_recupera_na_segunda_tentativa(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_http_error(500, '{"error": "interno"}'),
            _fake_response({"results": [], "total_pages": 1}),
        ]
        client = DentalClient(self._config(DENTAL_MAX_RETRIES=3))

        resposta = client.listar_pacientes(clinic_id=1)

        self.assertEqual(resposta["total_pages"], 1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_timeout_levanta_dental_timeout_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            TimeoutError("tempo esgotado"),
            TimeoutError("tempo esgotado"),
            TimeoutError("tempo esgotado"),
        ]
        client = DentalClient(self._config(DENTAL_MAX_RETRIES=3))

        with self.assertRaises(DentalTimeoutError):
            client.listar_pacientes(clinic_id=1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_falha_de_conexao_levanta_dental_connection_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            URLError("recusado"),
            URLError("recusado"),
            URLError("recusado"),
        ]
        client = DentalClient(self._config(DENTAL_MAX_RETRIES=3))

        with self.assertRaises(DentalConnectionError):
            client.listar_pacientes(clinic_id=1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_resposta_nao_json_levanta_invalid_response(
        self, mock_urlopen: MagicMock
    ) -> None:
        corpo_invalido = MagicMock()
        corpo_invalido.read.return_value = b"<html>erro</html>"
        corpo_invalido.status = 200
        corpo_invalido.__enter__.return_value = corpo_invalido
        mock_urlopen.side_effect = [_fake_response({"token": "tok-1"}), corpo_invalido]
        client = DentalClient(self._config())

        with self.assertRaises(DentalInvalidResponseError):
            client.listar_pacientes(clinic_id=1)

    @patch("gestao_lab.integrations.dental.urlopen")
    def test_post_nao_repete_em_erro_transitorio(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = [
            _fake_response({"token": "tok-1"}),
            _fake_http_error(500, '{"error": "interno"}'),
        ]
        client = DentalClient(self._config(DENTAL_MAX_RETRIES=3))

        with self.assertRaises(DentalServerError):
            client.enviar_documento_paciente(1, b"dados", "arq.pdf")

        # 1 chamada de autenticação + exatamente 1 tentativa de POST (sem retry)
        self.assertEqual(mock_urlopen.call_count, 2)


class BuscarEImportarMultiplasPaginasTests(TestCase):
    """Cobre a correção do bug: buscar_e_importar_* agora consolida todas as
    páginas retornadas pela API, não só a primeira."""

    def _item_paciente(self, id_: int) -> dict:
        return {
            "id": id_,
            "name": f"Paciente {id_}",
            "active": True,
            "contacts_attributes": [],
        }

    def _item_aluno(self, id_: int) -> dict:
        return {"id": id_, "name": f"Aluno {id_}", "contacts_attributes": []}

    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_busca_de_pacientes_consolida_todas_as_paginas(
        self, MockClient: MagicMock
    ) -> None:
        mock_client = MockClient.return_value
        mock_client.listar_pacientes.side_effect = [
            {
                "results": [self._item_paciente(i) for i in range(1, 61)],
                "total_pages": 2,
            },
            {"results": [self._item_paciente(61)], "total_pages": 2},
        ]

        resultado = buscar_e_importar_pacientes(q="Paciente", clinic_id=1)

        self.assertEqual(resultado["criados"], 61)
        self.assertEqual(Paciente.objects.count(), 61)
        self.assertEqual(mock_client.listar_pacientes.call_count, 2)

    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_busca_de_pacientes_com_uma_pagina_so_chama_uma_vez(
        self, MockClient: MagicMock
    ) -> None:
        mock_client = MockClient.return_value
        mock_client.listar_pacientes.return_value = {
            "results": [self._item_paciente(1)],
            "total_pages": 1,
        }

        resultado = buscar_e_importar_pacientes(q="Paciente", clinic_id=1)

        self.assertEqual(resultado["criados"], 1)
        mock_client.listar_pacientes.assert_called_once()

    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_busca_de_alunos_consolida_todas_as_paginas(
        self, MockClient: MagicMock
    ) -> None:
        mock_client = MockClient.return_value
        mock_client.listar_usuarios.side_effect = [
            {
                "results": [self._item_aluno(i) for i in range(1, 61)],
                "total_pages": 2,
            },
            {"results": [self._item_aluno(61)], "total_pages": 2},
        ]

        resultado = buscar_e_importar_alunos(q="Aluno", user_group=8)

        self.assertEqual(resultado["criados"], 61)
        self.assertEqual(AlunoLab.objects.count(), 61)
        self.assertEqual(mock_client.listar_usuarios.call_count, 2)


# ---------------------------------------------------------------------------
# Fase 3.3 — busca com seleção e exclusão de pedidos/moldagens
# ---------------------------------------------------------------------------


class SincronizacaoAgendadaDentalTests(TestCase):
    """A rotina em segundo plano que mantem as listagens do lab em dia."""

    @override_settings(DENTAL_CLINIC_ID=7, DENTAL_USER_GROUP_ALUNO=8)
    @patch("gestao_lab.services.dental_sync.sincronizar_alunos")
    @patch("gestao_lab.services.dental_sync.sincronizar_pacientes")
    def test_task_sincroniza_e_registra_no_historico(self, mock_pac, mock_alu) -> None:
        mock_pac.return_value = {"criados": 3, "atualizados": 10, "ignorados": 0}
        mock_alu.return_value = {"criados": 1, "atualizados": 4, "ignorados": 0}

        resumo = sincronizar_dental_task()

        self.assertEqual(resumo["pacientes_criados"], 3)
        self.assertEqual(resumo["alunos_atualizados"], 4)

        # a execucao automatica alimenta o mesmo historico exibido na interface
        registro = RegistroSync.objects.latest("criado_em")
        self.assertEqual(registro.tipo, RegistroSync.Tipo.AGENDADA)
        self.assertEqual(registro.disparado_por, "agendamento")
        self.assertTrue(registro.sucesso)

    @override_settings(DENTAL_CLINIC_ID=None)
    @patch("gestao_lab.services.dental_sync.sincronizar_pacientes")
    def test_task_nao_faz_nada_sem_configuracao(self, mock_pac) -> None:
        self.assertIsNone(sincronizar_dental_task())
        mock_pac.assert_not_called()


@override_settings(ALLOWED_HOSTS=["testserver"])
class BuscaSelecaoLabTests(TestCase):
    """Autocomplete de paciente e aluno nos formulários de pedido/moldagem."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="lab-3-3", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.pac = _paciente(nome="Maria Aparecida", id_dental="P1")
        _paciente(nome="Outro Paciente", id_dental="P2")
        self.aluno = _aluno(nome="Joao Pedro", id_dental="A1", celular="62999")
        _aluno(nome="Outro Aluno", id_dental="A2")

    @patch("gestao_lab.services.dental_sync.procurar_pacientes")
    def test_buscar_pacientes_filtra_por_nome(self, mock_procurar) -> None:
        mock_procurar.return_value = ([], 1)
        response = self.client.get(reverse("lab_buscar_pacientes"), {"q": "Maria"})

        self.assertContains(response, "Maria Aparecida")
        self.assertNotContains(response, "Outro Paciente")

    @patch("gestao_lab.services.dental_sync.procurar_alunos")
    def test_buscar_alunos_lab_filtra_por_nome(self, mock_procurar) -> None:
        mock_procurar.return_value = ([], 1)
        response = self.client.get(reverse("lab_buscar_alunos_lab"), {"q": "Joao"})

        self.assertContains(response, "Joao Pedro")
        self.assertNotContains(response, "Outro Aluno")

    def test_form_pedido_usa_autocomplete_e_nao_select(self) -> None:
        response = self.client.get(reverse("lab_criar_pedido"))
        conteudo = response.content.decode()

        self.assertIn("data-ac-hidden", conteudo)
        self.assertNotIn('<select id="id_paciente"', conteudo)

    def test_campos_de_busca_enviam_o_termo(self) -> None:
        """Regressão: sem `name` no input, o HTMX não envia `q` e a lista nunca
        filtra — a busca parece 'não atualizar'."""

        for rota in ("lab_criar_pedido", "lab_criar_moldagem"):
            with self.subTest(rota=rota):
                conteudo = self.client.get(reverse(rota)).content.decode()
                # Só os campos do autocomplete (a sidebar de importação do
                # Dental Office também tem campos de busca, mas sem HTMX).
                campos = re.findall(
                    r"<input[^>]*id=\"ac-busca-[^\"]+\"[^>]*>", conteudo
                )

                self.assertEqual(len(campos), 2, "esperados 2 campos de autocomplete")
                for campo in campos:
                    self.assertIn('name="q"', campo)
                    self.assertIn("hx-get=", campo)

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.procurar_pacientes")
    def test_busca_junta_base_local_e_api_sem_gravar(self, mock_procurar) -> None:
        """A lista e unica: o operador nao distingue quem ja estava no banco de
        quem veio da API — e a busca em si nao grava nada."""

        mock_procurar.return_value = (
            [PacienteDental(id=999, nome="Gustavo Só na API", celular="", ativo=True)],
            1,
        )
        antes = Paciente.objects.count()

        response = self.client.get(reverse("lab_buscar_pacientes"), {"q": "a"})
        conteudo = response.content.decode()

        self.assertContains(response, "Gustavo Só na API")  # veio da API
        self.assertContains(response, "Maria Aparecida")  # ja estava no banco
        self.assertIn('data-id-dental="999"', conteudo)
        # o item que ainda nao existe por aqui vai sem pk (grava so no clique)
        self.assertIn('data-id="" data-id-dental="999"', " ".join(conteudo.split()))
        self.assertEqual(Paciente.objects.count(), antes, "a busca nao pode gravar")

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.procurar_pacientes")
    def test_busca_avisa_quando_ha_mais_paginas(self, mock_procurar) -> None:
        mock_procurar.return_value = (
            [PacienteDental(id=1, nome="Silva Um", celular="", ativo=True)],
            4,
        )

        response = self.client.get(reverse("lab_buscar_pacientes"), {"q": "silva"})

        self.assertContains(response, "Há mais resultados")

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.procurar_pacientes")
    def test_busca_degrada_para_a_base_local_se_a_api_falhar(
        self, mock_procurar
    ) -> None:
        """Sem a API, quem ja esta no banco continua encontravel — com aviso."""

        mock_procurar.side_effect = DentalAPIError("indisponível")

        response = self.client.get(reverse("lab_buscar_pacientes"), {"q": "Maria"})

        self.assertContains(response, "Maria Aparecida")
        self.assertContains(response, "podem não aparecer")

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_selecionar_grava_apenas_o_escolhido(self, mock_client) -> None:
        """O registro so vai para o banco quando o operador escolhe — um write."""

        mock_client.return_value.buscar_detalhes_paciente.return_value = {
            "id": 999,
            "name": "Gustavo Escolhido",
            "active": True,
        }
        antes = Paciente.objects.count()

        response = self.client.post(
            reverse("lab_materializar", args=["paciente"]),
            {"id_dental": "999", "nome": "Gustavo Escolhido"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Paciente.objects.count(), antes + 1)
        criado = Paciente.objects.get(id_dental="999")
        self.assertEqual(response.json()["pk"], criado.pk)
        self.assertEqual(criado.nome, "Gustavo Escolhido")
        # dados vem da API, nunca do que o navegador mandou
        mock_client.return_value.buscar_detalhes_paciente.assert_called_once_with("999")

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_selecionar_registro_ja_existente_nao_chama_a_api(
        self, mock_client
    ) -> None:
        antes = Paciente.objects.count()

        response = self.client.post(
            reverse("lab_materializar", args=["paciente"]),
            {"id_dental": self.pac.id_dental, "nome": self.pac.nome},
        )

        self.assertEqual(response.json()["pk"], self.pac.pk)
        self.assertEqual(Paciente.objects.count(), antes)
        mock_client.return_value.buscar_detalhes_paciente.assert_not_called()

    @override_settings(DENTAL_CLINIC_ID=1)
    @patch("gestao_lab.services.dental_sync.DentalClient")
    def test_selecionar_devolve_erro_tratado_se_a_api_falhar(self, mock_client) -> None:
        mock_client.return_value.buscar_detalhes_paciente.side_effect = DentalAPIError(
            "fora do ar"
        )

        response = self.client.post(
            reverse("lab_materializar", args=["paciente"]),
            {"id_dental": "999", "nome": "Alguém"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Não foi possível", response.json()["erro"])

    def test_pedido_aceita_pk_vindo_do_campo_oculto(self) -> None:
        equipe = _equipe()
        lab = _laboratorio(equipe=equipe)
        response = self.client.post(
            reverse("lab_criar_pedido"),
            {
                "paciente": self.pac.pk,
                "aluno": self.aluno.pk,
                "laboratorio": lab.pk,
                "equipe": equipe.pk,
                "previsao_entrega": (date.today() + timedelta(days=5)).isoformat(),
                "descricao_servico": "Serviço de teste",
            },
        )

        self.assertRedirects(response, reverse("lab_pedidos"))
        self.assertEqual(PedidoMaterial.objects.count(), 1)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ExclusaoLabTests(TestCase):
    """Exclusão de pedidos e moldagens a partir das listagens."""

    def setUp(self) -> None:
        self.usuario = get_user_model().objects.create_user(
            username="lab-excluir", password="senha-segura"
        )
        self.client.force_login(self.usuario)
        self.pac = _paciente(id_dental="P9")
        self.aluno = _aluno(id_dental="A9")
        self.equipe = _equipe()
        self.lab = _laboratorio(equipe=self.equipe)

    def test_excluir_pedido_remove_registro(self) -> None:
        pedido = _pedido(self.pac, self.aluno, self.lab, self.equipe)

        response = self.client.post(reverse("lab_excluir_pedido", args=[pedido.pk]))

        self.assertRedirects(response, reverse("lab_pedidos"))
        self.assertFalse(PedidoMaterial.objects.filter(pk=pedido.pk).exists())

    def test_excluir_pedido_devolve_moldagem_para_nao_convertida(self) -> None:
        pedido = _pedido(self.pac, self.aluno, self.lab, self.equipe)
        moldagem = Moldagem.objects.create(
            paciente=self.pac, aluno=self.aluno, pedido_material=pedido
        )

        self.client.post(reverse("lab_excluir_pedido", args=[pedido.pk]))

        moldagem.refresh_from_db()
        self.assertIsNone(moldagem.pedido_material)
        self.assertFalse(moldagem.convertida)

    def test_excluir_moldagem_remove_registro(self) -> None:
        moldagem = Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)

        response = self.client.post(reverse("lab_excluir_moldagem", args=[moldagem.pk]))

        self.assertRedirects(response, reverse("lab_moldagens"))
        self.assertFalse(Moldagem.objects.filter(pk=moldagem.pk).exists())

    def test_exclusao_respeita_next(self) -> None:
        moldagem = Moldagem.objects.create(paciente=self.pac, aluno=self.aluno)
        destino = reverse("lab_moldagens") + "?filtro=nao_convertida"

        response = self.client.post(
            reverse("lab_excluir_moldagem", args=[moldagem.pk]), {"next": destino}
        )

        self.assertRedirects(response, destino)
