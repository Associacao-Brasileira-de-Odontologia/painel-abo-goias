"""Testes dos utilitários compartilhados."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from comum.http import destino_seguro
from gestao_cme.models import Aluno, OrigemDados, Turma


class DestinoSeguroTests(TestCase):
    """Cobre o helper que valida o ``next`` recebido dos formulários.

    O caso central é o ``//host-externo``: ele passa pela checagem antiga
    (``startswith("/")``) mas é uma URL protocol-relative, ou seja, o
    navegador a resolve como endereço externo — era por ali que o open
    redirect entrava (A-01/S-01).
    """

    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _destino(self, next_valor: str | None, padrao: str = "cme_home") -> str:
        dados = {} if next_valor is None else {"next": next_valor}
        return destino_seguro(self.factory.post("/qualquer/", dados), padrao)

    def test_caminho_interno_e_preservado(self) -> None:
        self.assertEqual(
            self._destino("/gestao-cme/movimentacoes/?status=pendente"),
            "/gestao-cme/movimentacoes/?status=pendente",
        )

    def test_sem_next_usa_o_padrao(self) -> None:
        self.assertEqual(self._destino(None), "cme_home")

    def test_next_vazio_ou_em_branco_usa_o_padrao(self) -> None:
        self.assertEqual(self._destino(""), "cme_home")
        self.assertEqual(self._destino("   "), "cme_home")

    def test_url_protocol_relative_e_recusada(self) -> None:
        # O caso que a checagem antiga deixava passar.
        self.assertEqual(self._destino("//evil.example.com/phishing"), "cme_home")

    def test_url_absoluta_externa_e_recusada(self) -> None:
        self.assertEqual(self._destino("https://evil.example.com/"), "cme_home")

    def test_barra_invertida_e_recusada(self) -> None:
        self.assertEqual(self._destino("\\\\evil.example.com"), "cme_home")

    def test_host_do_proprio_site_e_aceito(self) -> None:
        req = self.factory.post("/qualquer/", {"next": "http://testserver/abrigos/"})
        self.assertEqual(destino_seguro(req, "cme_home"), "http://testserver/abrigos/")


class RedirectDeViewRealTests(TestCase):
    """Confirma o efeito da correção passando por uma view de verdade."""

    def setUp(self) -> None:
        turma = Turma.objects.create(
            codigo="T-RED", nome="Turma Redirect", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            matricula="M-RED", nome="Aluno Redirect", turma=turma,
            origem=OrigemDados.MANUAL,
        )
        usuario = get_user_model().objects.create_user(
            username="coord-redirect", password="senha-segura"
        )
        self.client.force_login(usuario)
        self.url = reverse("atribuir_abrigo", args=[self.aluno.pk])

    def test_next_interno_continua_funcionando(self) -> None:
        destino = reverse("alunos_por_turma") + "?q=teste"
        resposta = self.client.post(self.url, {"abrigo_id": "", "next": destino})
        self.assertRedirects(resposta, destino)

    def test_next_externo_cai_no_padrao_em_vez_de_sair_do_site(self) -> None:
        resposta = self.client.post(
            self.url, {"abrigo_id": "", "next": "//evil.example.com/phishing"}
        )
        self.assertRedirects(resposta, reverse("alunos_por_turma"))
