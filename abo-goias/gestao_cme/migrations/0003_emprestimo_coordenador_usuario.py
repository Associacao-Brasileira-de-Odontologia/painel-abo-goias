# Generated manually for coordinator authentication bootstrap.
#
# Historicamente esta migration criava um usuario "coordenador.teste" com
# senha fixa via RunPython. Isso vazou uma credencial real no historico do
# repositorio e criava a mesma conta com a mesma senha em qualquer banco
# onde `migrate` fosse executado, inclusive producao. A funcao foi
# neutralizada (no-op) para que novos bancos nunca mais criem essa conta.
# Bancos onde ela ja foi criada sao limpos pela migration
# 0011_remover_usuario_coordenador_teste.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0002_emprestimo_itememprestimo"),
    ]

    operations = [
        migrations.AddField(
            model_name="emprestimo",
            name="coordenador_usuario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="emprestimos_realizados",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
