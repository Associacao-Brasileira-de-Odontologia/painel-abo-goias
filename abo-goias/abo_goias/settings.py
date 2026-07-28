import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    for env_file in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value == "":
        return default
    return value.lower() in {"1", "true", "yes", "sim", "on"}


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    value = _env(name)
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _database_from_url(database_url: str) -> dict[str, str | int]:
    parsed = urlparse(database_url)
    query = dict(parse_qsl(parsed.query))

    if parsed.scheme in {"sqlite", "sqlite3"}:
        if parsed.path in {"", "/"}:
            name = BASE_DIR / "db.sqlite3"
        elif parsed.path == "/:memory:":
            name = ":memory:"
        else:
            name = parsed.path.lstrip("/") if parsed.netloc else parsed.path
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(name),
        }

    engines = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
    }
    engine = engines.get(parsed.scheme)
    if not engine:
        raise ImproperlyConfigured(
            f"Banco de dados nao suportado em DATABASE_URL: {parsed.scheme}"
        )

    database = {
        "ENGINE": engine,
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }
    if query:
        database["OPTIONS"] = query
    return database


def _database_config() -> dict[str, dict]:
    database_url = _env("DATABASE_URL")
    if database_url:
        return {"default": _database_from_url(database_url)}

    db_engine = _env("DB_ENGINE")
    if db_engine:
        return {
            "default": {
                "ENGINE": db_engine,
                "NAME": _env("DB_NAME"),
                "USER": _env("DB_USER"),
                "PASSWORD": _env("DB_PASSWORD"),
                "HOST": _env("DB_HOST"),
                "PORT": _env("DB_PORT"),
            }
        }

    pg_database = _env("PGDATABASE")
    if pg_database:
        return {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": pg_database,
                "USER": _env("PGUSER"),
                "PASSWORD": _env("PGPASSWORD"),
                "HOST": _env("PGHOST"),
                "PORT": _env("PGPORT", "5432"),
            }
        }

    if not _env_bool("DJANGO_DEBUG", True):
        raise ImproperlyConfigured(
            "Nenhum banco de dados persistente configurado (DATABASE_URL, "
            "DB_ENGINE ou PGDATABASE) com DJANGO_DEBUG=false. Em produção "
            "isso cairia silenciosamente num SQLite local, que é apagado a "
            "cada reinício do container (filesystem efêmero no Railway) — "
            "resultando em erros como 'no such table: django_session' assim "
            "que o container reinicia. Configure DATABASE_URL apontando "
            "para um banco persistente (ex.: o plugin PostgreSQL do "
            "Railway, conectado a este serviço)."
        )

    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }


_load_env_file()


# Quick-start development settings - unsuitable for production.
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

DEBUG = _env_bool("DJANGO_DEBUG", True)

SECRET_KEY = _env(
    "DJANGO_SECRET_KEY",
    (
        "django-insecure-5o#=*kk7080r&^=1zdm^m007xxurh+n4df0a54@n_fiqfs3mbv"
        if DEBUG
        else ""
    ),
)
if not SECRET_KEY:
    raise ImproperlyConfigured("Defina DJANGO_SECRET_KEY no ambiente de producao.")

ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"] if DEBUG else []
)
RAILWAY_PUBLIC_DOMAIN = _env("RAILWAY_PUBLIC_DOMAIN")

# Adicionar domínio público do Railway se estiver definido
if RAILWAY_PUBLIC_DOMAIN and RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

# Adicionar sempre healthcheck do Railway
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Defina DJANGO_ALLOWED_HOSTS no ambiente de producao.")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "contas.apps.ContasConfig",
    "gestao_cme.apps.GestaoCmeConfig",
    "gestao_lab.apps.GestaoLabConfig",
    "gestao_contratos.apps.GestaoContratosConfig",
    "identificadores",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if importlib.util.find_spec("whitenoise"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "abo_goias.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "contas.context_processors.usuario_logado",
            ],
        },
    },
]

WSGI_APPLICATION = "abo_goias.wsgi.application"


DATABASES = _database_config()


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = _env("DJANGO_LANGUAGE_CODE", "pt-br")

TIME_ZONE = "America/Sao_Paulo"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = _env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_ROOT = Path(_env("DJANGO_MEDIA_ROOT", str(BASE_DIR)))
MEDIA_URL = "/media/"

# O storage com manifesto (hash no nome do arquivo) exige que `collectstatic`
# tenha rodado: sem o manifesto, qualquer {% static %} quebra. Isso e o que
# queremos em producao (erro alto se faltar arquivo), mas na suite de testes
# obrigaria um `collectstatic` previo so para renderizar templates. Por isso o
# manifesto fica desligado ao rodar os testes, mantendo a checagem estrita no
# resto dos ambientes.
TESTANDO = "test" in sys.argv[1:2]

if importlib.util.find_spec("whitenoise") and not TESTANDO:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Sessao expira apos 8h (turno de trabalho) e tambem ao fechar o navegador;
# antes disso o cookie de sessao usava o padrao do Django (2 semanas), o que
# nao fazia sentido para um sistema que manipula dados de pacientes.
SESSION_COOKIE_AGE = _env_int("DJANGO_SESSION_COOKIE_AGE", 60 * 60 * 8)
SESSION_EXPIRE_AT_BROWSER_CLOSE = _env_bool(
    "DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", True
)

EMAIL_HOST = _env("EMAIL_HOST") or _env("DJANGO_EMAIL_HOST")
EMAIL_PORT = _env_int("EMAIL_PORT", 0) or _env_int("DJANGO_EMAIL_PORT", 587)
EMAIL_HOST_USER = _env("EMAIL_HOST_USER") or _env("DJANGO_EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = _env("EMAIL_HOST_PASSWORD") or _env("DJANGO_EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = (
    _env_bool("EMAIL_USE_TLS", True)
    if _env("EMAIL_USE_TLS")
    else _env_bool("DJANGO_EMAIL_USE_TLS", True)
)
EMAIL_USE_SSL = (
    _env_bool("EMAIL_USE_SSL", False)
    if _env("EMAIL_USE_SSL")
    else _env_bool("DJANGO_EMAIL_USE_SSL", False)
)
DEFAULT_FROM_EMAIL = (
    _env("DEFAULT_FROM_EMAIL")
    or _env("DJANGO_DEFAULT_FROM_EMAIL")
    or "noreply@abogoias.local"
)

# E-mails que recebem a notificação de novas solicitações de acesso
# (contas.solicitar_acesso) — separados por vírgula. Sem esta variável,
# a notificação por e-mail simplesmente não é enviada; a solicitação
# continua visível normalmente no Django Admin.
ADMINS = [(email, email) for email in _env_list("DJANGO_ADMINS_EMAIL")]

# Usa SMTP automaticamente quando EMAIL_HOST estiver definido; console em DEBUG
if _env("DJANGO_EMAIL_BACKEND"):
    EMAIL_BACKEND = _env("DJANGO_EMAIL_BACKEND")
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Adicionar origens do Railway automaticamente
if RAILWAY_PUBLIC_DOMAIN:
    railway_origin = f"https://{RAILWAY_PUBLIC_DOMAIN}"
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)

# Permitir healthcheck do Railway
if "https://healthcheck.railway.app" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://healthcheck.railway.app")

SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = _env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = _env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = _env_int("DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG
)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if _env_bool("DJANGO_SECURE_PROXY_SSL_HEADER", False)
    else None
)

# Quantos proxies confiaveis existem entre o cliente e a aplicacao. Define
# qual entrada do X-Forwarded-For e o IP de origem real: o cabecalho cresce da
# esquerda para a direita e so as entradas acrescentadas pelos proxies
# confiaveis nao podem ser forjadas pelo cliente (ver _ip_do_request em
# gestao_contratos/views_assinatura.py). O padrao 1 vale para o Railway e para
# qualquer PaaS com um unico proxy de borda; use 0 quando a aplicacao receber
# conexoes diretas, para ignorar o cabecalho por completo.
PROXIES_CONFIAVEIS = _env_int("DJANGO_PROXIES_CONFIAVEIS", 1)

# Credenciais e parametros de todas as integracoes externas (WhatsApp, carimbo
# de tempo, Dental Office, Eduq) sao lidos aqui, centralizados num unico ponto
# de configuracao, em vez de cada servico ler os.environ (e recarregar o
# .env) diretamente. Os flags *_CONFIGURADO permitem que views/templates
# verifiquem se uma integracao esta ativa sem duplicar a logica de "campos
# obrigatorios".
# Z-API (envio automático de WhatsApp) — ver mensageria/ (pacote compartilhado
# entre apps, na raiz do projeto).
ZAPI_INSTANCE_ID = _env("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = _env("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = _env("ZAPI_CLIENT_TOKEN")
ZAPI_BASE_URL = _env("ZAPI_BASE_URL", "https://api.z-api.io")
ZAPI_TIMEOUT = _env_int("ZAPI_TIMEOUT", 30)
ZAPI_MAX_RETRIES = _env_int("ZAPI_MAX_RETRIES", 3)
ZAPI_RETRY_BACKOFF_SECONDS = _env_int("ZAPI_RETRY_BACKOFF_SECONDS", 2)
ZAPI_CONFIGURADO = bool(ZAPI_INSTANCE_ID and ZAPI_TOKEN)

CARIMBO_TEMPO_TSA_URL = _env("CARIMBO_TEMPO_TSA_URL")
CARIMBO_TEMPO_TSA_USERNAME = _env("CARIMBO_TEMPO_TSA_USERNAME")
CARIMBO_TEMPO_TSA_PASSWORD = _env("CARIMBO_TEMPO_TSA_PASSWORD")
CARIMBO_TEMPO_TIMEOUT = _env_int("CARIMBO_TEMPO_TIMEOUT", 30)
CARIMBO_TEMPO_CONFIGURADO = bool(CARIMBO_TEMPO_TSA_URL)

DENTAL_SYNC_TOKEN = _env("DENTAL_SYNC_TOKEN")
DENTAL_CLINIC_ID = _env_int("DENTAL_CLINIC_ID", 1)
DENTAL_USER_GROUP_ALUNO = _env_int("DENTAL_USER_GROUP_ALUNO", 8)
DENTAL_CLIENT_ID = _env("DENTAL_CLIENT_ID")
DENTAL_SECRET = _env("DENTAL_SECRET")
DENTAL_AUTH_URL = _env(
    "DENTAL_AUTH_URL",
    "https://demo.api.app.dentaloffice.com.br/v1/auth/tokens",
)
DENTAL_BASE_URL = _env(
    "DENTAL_BASE_URL",
    "https://demo.api.app.dentaloffice.com.br/v1",
)
DENTAL_VERIFY_TLS = _env_bool("DENTAL_VERIFY_TLS", True)
DENTAL_TIMEOUT = _env_int("DENTAL_TIMEOUT", 30)
DENTAL_USE_PROXY = _env_bool("DENTAL_USE_PROXY", False)
# Retry com backoff exponencial para falhas transitorias (timeout,
# indisponibilidade, limite de requisicoes) em chamadas de leitura (GET) —
# nunca aplicado a POST, para nao arriscar duplicar envios de documento.
DENTAL_MAX_RETRIES = _env_int("DENTAL_MAX_RETRIES", 3)
DENTAL_RETRY_BACKOFF_SECONDS = _env_int("DENTAL_RETRY_BACKOFF_SECONDS", 1)
DENTAL_CONFIGURADO = bool(DENTAL_CLIENT_ID and DENTAL_SECRET)

EDUQ_DOMINIO = _env("EDUQ_DOMINIO")
EDUQ_USUARIO = _env("EDUQ_USUARIO")
EDUQ_SENHA = _env("EDUQ_SENHA")
EDUQ_AUTH_URL = _env(
    "EDUQ_AUTH_URL",
    "https://apisistema.eduqtecnologia.com.br/autenticacao/logar",
)
EDUQ_DATA_URL = _env(
    "EDUQ_DATA_URL",
    "https://apisistema.eduqtecnologia.com.br/emissao-consulta-personalizada/obter-dados",
)
EDUQ_CONSULTA_TURMAS_ID = _env_int("EDUQ_CONSULTA_TURMAS_ID", 4)
EDUQ_CONSULTA_DETALHES_TURMA_ID = _env_int("EDUQ_CONSULTA_DETALHES_TURMA_ID", 5)
EDUQ_VERIFY_TLS = _env_bool("EDUQ_VERIFY_TLS", False)
EDUQ_TIMEOUT = _env_int("EDUQ_TIMEOUT", 30)
EDUQ_USE_PROXY = _env_bool("EDUQ_USE_PROXY", False)
EDUQ_CONFIGURADO = bool(EDUQ_DOMINIO and EDUQ_USUARIO and EDUQ_SENHA)

# ──────────────────────────────────────────────────────────────────────────
# Celery — processamento assíncrono (envio ao Dental Office, limpeza de
# sessões de assinatura vencidas). Broker e result backend usam Redis;
# REDIS_URL é preenchida automaticamente pelo plugin Redis do Railway.
# ──────────────────────────────────────────────────────────────────────────
TESTING = "test" in sys.argv or bool(os.environ.get("PYTEST_CURRENT_TEST"))

CELERY_BROKER_URL = _env("CELERY_BROKER_URL") or _env(
    "REDIS_URL", "redis://localhost:6379/0"
)
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
# Só confirma a tarefa ao worker depois de concluída — uma queda do processo
# no meio da execução devolve a tarefa para a fila em vez de perdê-la.
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_MAX_TASKS_PER_CHILD = 200

# Em testes, executa as tarefas de forma síncrona e imediata, sem exigir um
# broker Redis rodando — mantém a suíte determinística e independente de infra.
# CELERY_TASK_EAGER_PROPAGATES fica no padrão (False) de propósito: .delay()
# é fire-and-forget tanto em produção quanto em teste — uma falha dentro da
# tarefa nunca deve estourar no código que a disparou.
#
# Fora dos testes, o mesmo modo pode ser ligado via CELERY_TASK_ALWAYS_EAGER=true
# no .env — útil para rodar o servidor de desenvolvimento (runserver) sem
# precisar de um Redis local. Em produção (Railway) essa variável deve ficar
# ausente, para que as tarefas realmente rodem no worker dedicado.
if TESTING or _env_bool("CELERY_TASK_ALWAYS_EAGER", False):
    CELERY_TASK_ALWAYS_EAGER = True

CELERY_BEAT_SCHEDULE = {
    "expirar-sessoes-assinatura-vencidas": {
        "task": "gestao_contratos.tasks.expirar_sessoes_vencidas_task",
        "schedule": 300.0,  # a cada 5 minutos
    },
    "expirar-terminais-vencidos": {
        "task": "gestao_contratos.tasks.expirar_terminais_vencidos_task",
        "schedule": 1800.0,  # a cada 30 minutos — TTL é de horas, não precisa de mais frequência
    },
    "cobrar-pedidos-de-material-atrasados": {
        "task": "gestao_lab.tasks.cobrar_pedidos_atrasados_task",
        "schedule": crontab(hour=9, minute=0),  # uma vez por dia, as 9h
    },
    # Mantem a base local em dia sem ninguem precisar sincronizar na mao.
    # De madrugada (fora do horario de atendimento) e escalonadas: sao rotinas
    # longas, que percorrem todas as turmas do Eduq e todas as paginas do Dental
    # Office — nao convem dispara-las juntas (nem as duas consultas ao Eduq,
    # do CME e do laboratorio, uma sobre a outra).
    "atualizar-turmas-e-alunos-eduq": {
        "task": "gestao_cme.tasks.sincronizar_eduq_task",
        "schedule": crontab(hour=4, minute=0),
    },
    "atualizar-turmas-e-alunos-eduq-lab": {
        "task": "gestao_lab.tasks.sincronizar_eduq_lab_task",
        "schedule": crontab(hour=4, minute=15),
    },
    "atualizar-pacientes-dental": {
        "task": "gestao_lab.tasks.sincronizar_dental_task",
        "schedule": crontab(hour=4, minute=30),
    },
    # data_prevista_devolucao e um DateField (granularidade de dia), entao uma
    # vez por dia basta — a listagem de emprestimos roda a mesma regra a cada
    # acesso (views.emprestimos), esta tarefa so cobre quem nao visita a tela.
    "marcar-emprestimos-atrasados": {
        "task": "gestao_cme.tasks.marcar_emprestimos_atrasados_task",
        "schedule": crontab(hour=6, minute=0),
    },
}
