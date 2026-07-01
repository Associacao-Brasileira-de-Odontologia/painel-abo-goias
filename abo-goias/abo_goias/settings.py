import importlib.util
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "gestao_cme.context_processors.usuario_logado",
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
STATICFILES_DIRS = []

MEDIA_ROOT = Path(_env("DJANGO_MEDIA_ROOT", str(BASE_DIR)))
MEDIA_URL = "/media/"

if importlib.util.find_spec("whitenoise"):
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

DENTAL_SYNC_TOKEN = os.environ.get("DENTAL_SYNC_TOKEN", "")
DENTAL_CLINIC_ID = int(os.environ.get("DENTAL_CLINIC_ID", "1"))
DENTAL_USER_GROUP_ALUNO = int(os.environ.get("DENTAL_USER_GROUP_ALUNO", "8"))

DENTAL_AUTH_URL = os.environ.get(
    "DENTAL_AUTH_URL",
    "https://demo.api.app.dentaloffice.com.br/v1/auth/tokens",
)
DENTAL_BASE_URL = os.environ.get(
    "DENTAL_BASE_URL",
    "https://demo.api.app.dentaloffice.com.br/v1",
)
DENTAL_VERIFY_TLS = os.environ.get("DENTAL_VERIFY_TLS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "sim",
    "on",
}
DENTAL_TIMEOUT = int(os.environ.get("DENTAL_TIMEOUT", "30"))
DENTAL_USE_PROXY = os.environ.get("DENTAL_USE_PROXY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "sim",
    "on",
}

EDUQ_AUTH_URL = os.environ.get(
    "EDUQ_AUTH_URL",
    "https://apisistema.eduqtecnologia.com.br/autenticacao/logar",
)
EDUQ_DATA_URL = os.environ.get(
    "EDUQ_DATA_URL",
    "https://apisistema.eduqtecnologia.com.br/emissao-consulta-personalizada/obter-dados",
)
EDUQ_CONSULTA_TURMAS_ID = int(os.environ.get("EDUQ_CONSULTA_TURMAS_ID", "4"))
EDUQ_CONSULTA_DETALHES_TURMA_ID = int(
    os.environ.get("EDUQ_CONSULTA_DETALHES_TURMA_ID", "5")
)
EDUQ_VERIFY_TLS = os.environ.get("EDUQ_VERIFY_TLS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "sim",
    "on",
}
EDUQ_TIMEOUT = int(os.environ.get("EDUQ_TIMEOUT", "30"))
EDUQ_USE_PROXY = os.environ.get("EDUQ_USE_PROXY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "sim",
    "on",
}
