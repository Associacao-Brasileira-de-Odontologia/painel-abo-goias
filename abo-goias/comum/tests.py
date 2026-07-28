"""Testes dos utilitários compartilhados."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from comum.datas import filtrar_por_intervalo, parse_data_iso
from comum.http import destino_seguro
from comum.paginacao import paginar
from gestao_cme.models import Aluno, Emprestimo, Movimentacao, OrigemDados, Turma


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


class ParseDataIsoTests(TestCase):
    """Converte o valor cru de um ``<input type="date">`` em datetime aware."""

    def test_data_valida(self) -> None:
        dt = parse_data_iso("2026-07-28")
        self.assertIsNotNone(dt)
        self.assertEqual((dt.year, dt.month, dt.day), (2026, 7, 28))
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))
        self.assertTrue(timezone.is_aware(dt))

    def test_fim_do_dia_estica_ate_235959(self) -> None:
        dt = parse_data_iso("2026-07-28", fim_do_dia=True)
        self.assertEqual((dt.hour, dt.minute, dt.second), (23, 59, 59))

    def test_vazio_e_invalido_viram_none(self) -> None:
        self.assertIsNone(parse_data_iso(""))
        self.assertIsNone(parse_data_iso("28/07/2026"))
        self.assertIsNone(parse_data_iso("2026-13-45"))


class FiltrarPorIntervaloTests(TestCase):
    """Recorte por período, nos dois tipos de campo de data do projeto."""

    def setUp(self) -> None:
        turma = Turma.objects.create(
            codigo="T-INT", nome="Turma Intervalo", origem=OrigemDados.MANUAL
        )
        self.aluno = Aluno.objects.create(
            matricula="M-INT", nome="Aluno Intervalo", turma=turma,
            origem=OrigemDados.MANUAL,
        )
        self.hoje = timezone.localtime(timezone.now()).date()

    def _movimentacao(self, quando) -> Movimentacao:
        return Movimentacao.objects.create(
            data_hora=quando,
            tipo=Movimentacao.Tipo.ENTRADA,
            aluno=self.aluno,
            aluno_nome=self.aluno.nome,
            pacote_codigo="1",
            arquivo_origem="teste.csv",
            row_hash=f"hash-intervalo-{quando.isoformat()}",
            origem=OrigemDados.MANUAL,
        )

    def test_datetimefield_recorta_pelo_instante(self) -> None:
        agora = timezone.now()
        dentro = self._movimentacao(agora - timedelta(days=1))
        self._movimentacao(agora - timedelta(days=40))

        resultado = filtrar_por_intervalo(
            Movimentacao.objects.all(),
            "data_hora",
            agora - timedelta(days=7),
            None,
        )

        self.assertEqual(list(resultado), [dentro])

    def test_datefield_inclui_o_dia_inteiro_do_extremo_superior(self) -> None:
        """Num DateField, o último dia do intervalo entra inteiro.

        O fim do intervalo chega como 23:59:59 (ver ``parse_data_iso``), mas o
        campo guarda só a data — quem faz essa reconciliação é o próprio
        Django, no ``DateField.to_python``. O teste fixa o comportamento
        esperado na fronteira, que é o que importa para quem usa o filtro.
        """

        no_limite = Emprestimo.objects.create(
            aluno=self.aluno, data_prevista_devolucao=self.hoje
        )
        Emprestimo.objects.create(
            aluno=self.aluno, data_prevista_devolucao=self.hoje + timedelta(days=1)
        )

        resultado = filtrar_por_intervalo(
            Emprestimo.objects.all(),
            "data_prevista_devolucao",
            None,
            parse_data_iso(self.hoje.strftime("%Y-%m-%d"), fim_do_dia=True),
        )

        self.assertEqual(list(resultado), [no_limite])

    def test_sem_datas_devolve_o_queryset_intacto(self) -> None:
        self._movimentacao(timezone.now())
        base = Movimentacao.objects.all()

        self.assertEqual(
            list(filtrar_por_intervalo(base, "data_hora", None, None)), list(base)
        )


class PaginarTests(TestCase):
    """Pagina preservando os filtros da query string."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        turma = Turma.objects.create(
            codigo="T-PAG", nome="Turma Paginação", origem=OrigemDados.MANUAL
        )
        for i in range(7):
            Aluno.objects.create(
                matricula=f"M-PAG-{i}", nome=f"Aluno {i}", turma=turma,
                origem=OrigemDados.MANUAL,
            )

    def test_respeita_a_densidade_informada(self) -> None:
        pagina, _ = paginar(
            self.factory.get("/"), Aluno.objects.order_by("matricula"), 3
        )
        self.assertEqual(len(pagina.object_list), 3)
        self.assertEqual(pagina.paginator.num_pages, 3)

    def test_query_string_preserva_filtros_e_descarta_page(self) -> None:
        requisicao = self.factory.get("/", {"q": "ana", "status": "ativo", "page": "2"})

        pagina, query_string = paginar(requisicao, Aluno.objects.all(), 3)

        self.assertEqual(pagina.number, 2)
        self.assertIn("q=ana", query_string)
        self.assertIn("status=ativo", query_string)
        self.assertNotIn("page=", query_string)
