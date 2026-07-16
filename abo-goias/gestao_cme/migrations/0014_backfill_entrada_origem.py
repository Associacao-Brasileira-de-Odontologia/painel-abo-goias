"""Liga as SAIDAs ja existentes as suas ENTRADAs (dados do painel).

Ate aqui o vinculo entrada->saida so existia como coincidencia de
``pacote_codigo``. Este backfill materializa o vinculo em ``entrada_origem``
para os registros criados pelo painel, onde o codigo e uma sequencia numerica
global e identifica o pacote de fato.

Deliberadamente NAO toca em registros LEGADO: neles o ``pacote_codigo`` e o
codigo do **material** (ver services/migracao_legado.py), repetido entre alunos
e datas — parear por ele cruzaria registros de pessoas diferentes. Sem vinculo
real no dado, ficam nulos e a listagem os mostra soltos.

Tambem pula qualquer codigo ambiguo (mais de uma ENTRADA com o mesmo codigo e
mesmo aluno), possivel por causa da geracao sem lock (B-07 da auditoria): na
duvida sobre qual entrada parear, nao pareia.
"""

from __future__ import annotations

from django.db import migrations


def ligar_saidas_as_entradas(apps, schema_editor):
    Movimentacao = apps.get_model("core", "Movimentacao")

    entradas_por_chave: dict[tuple, list] = {}
    for entrada in Movimentacao.objects.filter(tipo="ENTRADA", origem="MANUAL"):
        chave = (entrada.pacote_codigo, entrada.aluno_id)
        entradas_por_chave.setdefault(chave, []).append(entrada)

    atualizadas = []
    for saida in Movimentacao.objects.filter(
        tipo="SAIDA", origem="MANUAL", entrada_origem__isnull=True
    ):
        candidatas = entradas_por_chave.get((saida.pacote_codigo, saida.aluno_id), [])
        # 0 candidatas: nada a ligar. >1: codigo ambiguo — nao adivinha.
        if len(candidatas) != 1:
            continue
        saida.entrada_origem = candidatas[0]
        atualizadas.append(saida)

    if atualizadas:
        Movimentacao.objects.bulk_update(atualizadas, ["entrada_origem"], batch_size=500)


def desligar(apps, schema_editor):
    Movimentacao = apps.get_model("core", "Movimentacao")
    Movimentacao.objects.filter(tipo="SAIDA").update(entrada_origem=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_movimentacao_entrada_origem"),
    ]

    operations = [
        migrations.RunPython(ligar_saidas_as_entradas, desligar),
    ]
