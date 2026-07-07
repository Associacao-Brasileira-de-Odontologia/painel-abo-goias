"""Bootstrap do Celery para a aplicação ABO Goiás.

Usado para processar em segundo plano o envio de contratos assinados ao
Dental Office (com retry automático) e a limpeza periódica de sessões de
assinatura vencidas. Veja gestao_contratos/tasks.py para as tarefas.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "abo_goias.settings")

app = Celery("abo_goias")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
