from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from gestao_cme.models import (
    Abrigo,
    Aluno,
    Armario,
    Emprestimo,
    EstoqueArmario,
    ItemEmprestimo,
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    OrigemDados,
    Turma,
)


class GestaoCMEModelTests(TestCase):
    def test_turma_usa_defaults_e_representacao_textual(self) -> None:
        turma = Turma.objects.create(codigo="END-2026", nome="Endodontia")

        self.assertEqual(str(turma), "END-2026 - Endodontia")
        self.assertEqual(turma.origem, OrigemDados.MANUAL)
        self.assertTrue(turma.ativo)
        self.assertIsNotNone(turma.criado_em)
        self.assertIsNotNone(turma.atualizado_em)

    def test_aluno_retorna_nome_e_pode_ser_vinculado_a_turma(self) -> None:
        turma = Turma.objects.create(codigo="IMP-2026", nome="Implantodontia")
        aluno = Aluno.objects.create(
            nome="Ana Clara",
            matricula="A-001",
            turma=turma,
            cidade="Goiania",
            uf="GO",
        )

        self.assertEqual(str(aluno), "Ana Clara")
        self.assertEqual(aluno.turma, turma)
        self.assertEqual(list(turma.alunos.all()), [aluno])

    def test_material_usa_defaults_operacionais(self) -> None:
        material = Material.objects.create(nome="Sonda", codigo="MAT-001")

        self.assertEqual(str(material), "Sonda")
        self.assertTrue(material.disponivel)
        self.assertEqual(material.unidade_medida, Material.UnidadeMedida.UNIDADE)
        self.assertEqual(material.quantidade_minima, 0)

    def test_kit_material_vincula_material_ao_kit_e_impede_duplicidade(self) -> None:
        kit = Kit.objects.create(nome="Kit Clinico", codigo="KIT-001")
        material = Material.objects.create(nome="Espelho", codigo="MAT-002")
        item = KitMaterial.objects.create(kit=kit, material=material, quantidade=2)

        self.assertEqual(str(kit), "Kit Clinico")
        self.assertEqual(str(item), "2 x Espelho")
        self.assertEqual(list(kit.materiais.all()), [material])
        self.assertEqual(list(material.kits.all()), [kit])

        with self.assertRaises(IntegrityError), transaction.atomic():
            KitMaterial.objects.create(kit=kit, material=material, quantidade=1)

    def test_armario_estoque_e_abrigos_tem_representacoes_basicas(self) -> None:
        armario = Armario.objects.create(
            identificacao="A1",
            localizacao="CME",
        )
        material = Material.objects.create(nome="Pinca", codigo="MAT-003")
        estoque = EstoqueArmario.objects.create(
            armario=armario,
            material=material,
            quantidade=5,
        )
        abrigo = Abrigo.objects.create(identificador="150", ocupado=True)

        self.assertEqual(str(armario), "A1")
        self.assertEqual(str(estoque), "A1 - Pinca: 5")
        self.assertEqual(str(abrigo), "150")
        self.assertEqual(list(armario.materiais.all()), [material])
        self.assertEqual(list(material.armarios.all()), [armario])

        with self.assertRaises(IntegrityError), transaction.atomic():
            EstoqueArmario.objects.create(
                armario=armario,
                material=material,
                quantidade=1,
            )

    def test_emprestimo_e_item_usam_status_default_e_relacionamentos(self) -> None:
        usuario = get_user_model().objects.create_user(username="coordenador")
        turma = Turma.objects.create(codigo="PER-2026", nome="Periodontia")
        aluno = Aluno.objects.create(nome="Bruno Lima", matricula="A-002", turma=turma)
        kit = Kit.objects.create(nome="Kit Periodontal", codigo="KIT-002")
        material = Material.objects.create(nome="Cureta", codigo="MAT-004")
        armario = Armario.objects.create(identificacao="B2")
        emprestimo = Emprestimo.objects.create(
            aluno=aluno,
            kit=kit,
            coordenador_usuario=usuario,
        )
        item = ItemEmprestimo.objects.create(
            emprestimo=emprestimo,
            material=material,
            armario=armario,
            quantidade=3,
        )

        self.assertEqual(emprestimo.status, Emprestimo.Status.EMPRESTADO)
        self.assertIn("Emprestimo #", str(emprestimo))
        self.assertIn("Bruno Lima", str(emprestimo))
        self.assertEqual(str(item), "3 x Cureta")
        self.assertEqual(list(emprestimo.itens.all()), [item])
        self.assertEqual(list(aluno.emprestimos.all()), [emprestimo])
        self.assertEqual(list(kit.emprestimos.all()), [emprestimo])

    def test_movimentacao_retorna_descricao_resumida(self) -> None:
        movimentacao = Movimentacao.objects.create(
            data_hora=timezone.now(),
            tipo=Movimentacao.Tipo.SAIDA,
            aluno_nome="Carla Souza",
            turma_nome="Dentistica",
            pacote_codigo="PCT-001",
            arquivo_origem="Relatorio.csv",
            row_hash="hash-model-movimentacao",
        )

        self.assertEqual(str(movimentacao), "Saida - PCT-001 - Carla Souza")
        self.assertEqual(movimentacao.origem, OrigemDados.LEGADO)
        self.assertTrue(movimentacao.ativo)
