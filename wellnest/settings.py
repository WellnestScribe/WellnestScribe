"""Django settings for the WellNest Scribe project."""

import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi
from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "apps"))

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-change-me-in-production-please-im-begging-you",
)
DEBUG = config("DEBUG", default=True, cast=bool)

def _normalize_allowed_hosts(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = (value or "").strip()
        if not item:
            continue
        if "://" in item:
            parsed = urlparse(item)
            item = parsed.netloc or parsed.path or item
        item = item.strip().strip("/")
        if item.count(":") == 1 and not item.startswith("["):
            item = item.split(":", 1)[0]
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_trusted_origins(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = (value or "").strip()
        if not item:
            continue
        if "://" not in item:
            item = f"https://{item.lstrip('/')}"
        item = item.rstrip("/")
        if item not in normalized:
            normalized.append(item)
    return normalized


ALLOWED_HOSTS = _normalize_allowed_hosts(
    config(
        "ALLOWED_HOSTS",
        default="wellnestscribe.com,www.wellnestscribe.com,localhost,127.0.0.1,0.0.0.0,.ngrok-free.app,6d59-72-27-184-245.ngrok-free.app",
        cast=Csv(),
    )
)

CSRF_TRUSTED_ORIGINS = _normalize_trusted_origins(
    config(
        "CSRF_TRUSTED_ORIGINS",
        default="https://wellnestscribe.com,https://www.wellnestscribe.com,https://*.ngrok-free.app,http://localhost:9093,http://127.0.0.1:9093",
        cast=Csv(),
    )
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "accounts",
    "emr",
    "scribe",
    "ed",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "wellnest.middleware.DemoLockdownMiddleware",
    "wellnest.middleware.SecurityAuditMiddleware",
    "wellnest.middleware.UsageContextMiddleware",
    "wellnest.middleware.EmrPlanGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wellnest.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "scribe.context_processors.ui_preferences",
            ],
        },
    },
]

WSGI_APPLICATION = "wellnest.wsgi.application"


def _mysql_ssl_options(host: str) -> dict:
    ssl_disabled = config("MYSQL_SSL_DISABLED", default=False, cast=bool)
    if ssl_disabled:
        return {"charset": "utf8mb4"}

    ssl_ca_path = config("MYSQL_SSL_CA_PATH", default="").strip()
    use_azure_ssl = "mysql.database.azure.com" in (host or "")
    if not ssl_ca_path and not use_azure_ssl:
        return {}

    return {
        "charset": "utf8mb4",
        "ssl": {"ca": ssl_ca_path or certifi.where()},
    }


def _database_from_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()
    if scheme.startswith("postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (parsed.path or "/").lstrip("/") or "wellnest",
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port) if parsed.port else "",
            "CONN_MAX_AGE": 60,
        }
    if scheme.startswith("mysql"):
        host = parsed.hostname or ""
        database = {
            "ENGINE": "django.db.backends.mysql",
            "NAME": (parsed.path or "/").lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": host,
            "PORT": str(parsed.port) if parsed.port else "3306",
            "CONN_MAX_AGE": 60,
        }
        options = _mysql_ssl_options(host)
        if options:
            database["OPTIONS"] = options
        return database
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


def _database_from_env() -> dict:
    database_url = config("DATABASE_URL", default="").strip()
    if database_url:
        return _database_from_url(database_url)

    use_sqlite = config("DJANGO_USE_SQLITE", default=True, cast=bool)
    if use_sqlite:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    host = config("AZURE_MYSQL_HOST", default="").strip()
    name = config("AZURE_MYSQL_NAME", default="").strip()
    user = config("AZURE_MYSQL_USER", default="").strip()
    password = config("AZURE_MYSQL_PASSWORD", default="")
    port = str(config("AZURE_MYSQL_PORT", default="3306")).strip() or "3306"

    missing = [
        key
        for key, value in {
            "AZURE_MYSQL_HOST": host,
            "AZURE_MYSQL_NAME": name,
            "AZURE_MYSQL_USER": user,
            "AZURE_MYSQL_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise ImproperlyConfigured(
            "Azure MySQL is enabled but the following settings are missing: "
            + ", ".join(missing)
        )

    database = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 60,
    }
    options = _mysql_ssl_options(host)
    if options:
        database["OPTIONS"] = options
    return database


DATABASES = {"default": _database_from_env()}

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = config("TIME_ZONE", default="America/Jamaica")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:signin"
LOGIN_REDIRECT_URL = "scribe:record"
LOGOUT_REDIRECT_URL = "accounts:signin"

DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024

# ---- HIPAA / GDPR-leaning security defaults ----
# Behind HTTPS in prod these tighten further; settings are conservative for local dev.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Must be False for AJAX — JS reads cookie to send X-CSRFToken header
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 4  # 4h max session lifetime (reduced from 8h for PHI compliance)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# Was True ("rolling expiry"), but that wrote the session to the DB on EVERY
# request (BEGIN/UPDATE/COMMIT = 3 round-trips) - a big per-request cost that made
# the whole app slow against a remote DB. Inactivity is already covered by the
# client-side idle-lock, so we keep an absolute 4h cap instead of rolling.
SESSION_SAVE_EVERY_REQUEST = config("SESSION_SAVE_EVERY_REQUEST", default=False, cast=bool)
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if not DEBUG else None
if not DEBUG:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True

# ---- PHI field encryption ----
# Generate once: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Then set FIELD_ENCRYPTION_KEY in .env or Azure App Service config.
# If absent, encrypted fields fall back to plaintext (safe for local dev).
FIELD_ENCRYPTION_KEY = config("FIELD_ENCRYPTION_KEY", default="")

# ---- django-axes: brute-force login protection ----
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5          # lock after 5 failed attempts
AXES_COOLOFF_TIME = 0.25        # 15-minute lockout (in hours as float)
AXES_LOCKOUT_CALLABLE = None    # use default 403 response
AXES_RESET_ON_SUCCESS = True    # clear failed count on successful login
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]  # lock per username+IP combo
AXES_VERBOSE = False

# Admin email for security alerts — set SECURITY_ALERT_EMAIL in .env
SECURITY_ALERT_EMAIL = config("SECURITY_ALERT_EMAIL", default="")

# Idle screen lock timeout (minutes). After this much inactivity the app
# shows a lock screen requiring password re-entry. Set to 0 to disable.
IDLE_LOCK_MINUTES = config("IDLE_LOCK_MINUTES", default=15, cast=int)

# ---- WellNest Scribe AI configuration ----
SCRIBE_USE_REAL_AI = config("SCRIBE_USE_REAL_AI", default=False, cast=bool)
SCRIBE_PIPELINE_MODE = config("SCRIBE_PIPELINE_MODE", default="single")  # single | modular
SCRIBE_VERIFIER_ENABLED = config("SCRIBE_VERIFIER_ENABLED", default=False, cast=bool)
SCRIBE_MAX_COMPLETION_TOKENS = config(
    "SCRIBE_MAX_COMPLETION_TOKENS", default=4000, cast=int
)

# Transcription is OpenAI direct (gpt-4o(-mini)-transcribe).
SCRIBE_TRANSCRIPTION_BACKEND = config(
    "SCRIBE_TRANSCRIPTION_BACKEND",
    default="openai",
)  # openai | lightning_mms
SCRIBE_OPENAI_API_KEY = config("SCRIBE_OPENAI_API_KEY", default="")
SCRIBE_OPENAI_TRANSCRIBE_MODEL = config(
    "SCRIBE_OPENAI_TRANSCRIBE_MODEL", default="gpt-4o-transcribe"
)
SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT = config(
    "SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT",
    default=config("AZURE_OPENAI_ENDPOINT", default=""),
)
SCRIBE_AZURE_OPENAI_TRANSCRIBE_KEY = config(
    "SCRIBE_AZURE_OPENAI_TRANSCRIBE_KEY",
    default=config("AZURE_OPENAI_KEY", default=""),
)
SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT = config(
    "SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT", default=""
)
SCRIBE_AZURE_OPENAI_TRANSCRIBE_API_VERSION = config(
    "SCRIBE_AZURE_OPENAI_TRANSCRIBE_API_VERSION", default="2024-06-01"
)
SCRIBE_LIGHTNING_TRANSCRIBE_URL = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_URL",
    default="",
)
SCRIBE_LIGHTNING_TRANSCRIBE_TOKEN = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_TOKEN",
    default="",
)
SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG",
    default="jam",
)
SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE",
    default="auto",
)
SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID",
    default="facebook/mms-1b-l1107",
)
SCRIBE_LIGHTNING_TRANSCRIBE_TIMEOUT = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_TIMEOUT",
    default=600,
    cast=int,
)
SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS = config(
    "SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS",
    default=25,
    cast=int,
)

# SOAP generation is Azure OpenAI deployment.
SCRIBE_AZURE_OPENAI_ENDPOINT = config(
    "SCRIBE_AZURE_OPENAI_ENDPOINT",
    default=config("AZURE_OPENAI_ENDPOINT", default=""),
)
SCRIBE_AZURE_OPENAI_KEY = config(
    "SCRIBE_AZURE_OPENAI_KEY",
    default=config("AZURE_OPENAI_KEY", default=""),
)
SCRIBE_AZURE_OPENAI_DEPLOYMENT = config(
    "SCRIBE_AZURE_OPENAI_DEPLOYMENT",
    default=config("AZURE_OPENAI_DEPLOYMENT_NAME", default="gpt-4o-mini"),
)
SCRIBE_AZURE_OPENAI_API_VERSION = config(
    "SCRIBE_AZURE_OPENAI_API_VERSION", default="2024-12-01-preview"
)
# Reasoning effort for note generation (reasoning models like gpt-5-mini only).
# minimal | low | medium | high. Higher = the model deliberates and cross-checks
# the transcript, which cuts fabrication on hard input (Patois) - at a small extra
# output-token cost. 'minimal' is fastest/cheapest but hallucinates most.
SCRIBE_REASONING_EFFORT = config("SCRIBE_REASONING_EFFORT", default="minimal")
# Opt 1: tell GPT-5 to skip writing Steps 1 & 3 in visible output (it reasons
# internally). Saves ~500-1 000 output tokens ≈ 5-8 s on the interpret call.
SCRIBE_SLIM_INTERPRET = config("SCRIBE_SLIM_INTERPRET", default=True, cast=bool)
# Opt 2: combine interpret + SOAP into a single GPT-5 call. Saves one full
# round-trip (~10-15 s). Disabled by default until battle-tested.
SCRIBE_COMBINED_PIPELINE = config("SCRIBE_COMBINED_PIPELINE", default=False, cast=bool)
# Opt 3: stream SOAP generation tokens to the browser via SSE so the doctor
# sees text appearing immediately instead of waiting for the full response.
SCRIBE_STREAM_GENERATION = config("SCRIBE_STREAM_GENERATION", default=False, cast=bool)

SCRIBE_MODE = config("SCRIBE_MODE", default="cloud")
PILOT_MODE = config("PILOT_MODE", default=True, cast=bool)
AUTO_DELETE_AUDIO_DAYS = config("AUTO_DELETE_AUDIO_DAYS", default=30, cast=int)

# ---- External EMR backend ----
# "local"      → WellnestScribe's built-in Django EMR (default, no extra setup)
# "gnuhealth"  → GNU Health via Docker (set GNUHEALTH_* vars below)
EMR_BACKEND = config("EMR_BACKEND", default="local")

GNUHEALTH_HOST = config("GNUHEALTH_HOST", default="localhost")
GNUHEALTH_PORT = config("GNUHEALTH_PORT", default=8069, cast=int)
GNUHEALTH_DB = config("GNUHEALTH_DB", default="gnuhealth")
GNUHEALTH_USER = config("GNUHEALTH_USER", default="admin")
GNUHEALTH_PASSWORD = config("GNUHEALTH_PASSWORD", default="")

# ---- Triage sandbox (admin/staff only by default) ----
# Set SCRIBE_ENABLE_TRIAGE=True in .env to expose to all logged-in users.
# Otherwise visible only to staff / superusers.
SCRIBE_ENABLE_TRIAGE = config("SCRIBE_ENABLE_TRIAGE", default=False, cast=bool)
TRIAGE_DEFAULT_DEVICE = config("TRIAGE_DEFAULT_DEVICE", default="cpu")  # cpu | cuda
TRIAGE_AUDIO_DIR = BASE_DIR / "media" / "triage"
TRIAGE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Modal GPU endpoints — ambient transcription.
# AMBIENT_BACKEND: modal-omni | modal | local
MODAL_MMS_URL = config("MODAL_MMS_URL", default="")
MODAL_MMS_API_KEY = config("MODAL_MMS_API_KEY", default="")
MODAL_OMNI_API_KEY = config("MODAL_OMNI_API_KEY", default="")
AMBIENT_BACKEND = config("AMBIENT_BACKEND", default="local")  # modal-omni | modal | local
OMNI_CACHE_DIR = config("OMNI_CACHE_DIR", default="")  # overrides FAIRSEQ2_CACHE_DIR for omniASR weights

# Omni profile URLs — same API, different Modal autoscaler configs.
# MODAL_OMNI_PROFILE selects which URL is used as MODAL_OMNI_URL.
# Set MODAL_OMNI_URL directly to bypass profile selection (legacy / override).
MODAL_OMNI_URL_LOW = config("MODAL_OMNI_URL_LOW", default="")   # cheap / dev / cold-starts OK
MODAL_OMNI_URL_MID = config("MODAL_OMNI_URL_MID", default="")   # balanced — default for normal usage
MODAL_OMNI_URL_HIGH = config("MODAL_OMNI_URL_HIGH", default="")  # clinic hours — always-warm container
MODAL_OMNI_PROFILE = config("MODAL_OMNI_PROFILE", default="low")  # low | mid | high
_OMNI_PROFILE_MAP = {
    "low": MODAL_OMNI_URL_LOW,
    "mid": MODAL_OMNI_URL_MID,
    "high": MODAL_OMNI_URL_HIGH,
}
# Profile URL wins; explicit MODAL_OMNI_URL is the fallback for backwards compat.
MODAL_OMNI_URL = _OMNI_PROFILE_MAP.get(MODAL_OMNI_PROFILE, "") or config("MODAL_OMNI_URL", default="")

# ---- Logging ----
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file_app": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "wellnest.log"),
            "maxBytes": 5_000_000,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "file_audit": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "audit.log"),
            "maxBytes": 5_000_000,
            "backupCount": 10,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file_app"],
            "level": "INFO",
            "propagate": False,
        },
        "scribe": {
            "handlers": ["console", "file_app"],
            "level": "INFO",
            "propagate": False,
        },
        "scribe.audit": {
            "handlers": ["file_audit", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ── Email / SMTP (appointment reminders, notifications) ──────────────────────
# Credentials are set later via env vars. Until EMAIL_HOST is provided, email
# falls back to the console backend so the reminder feature runs end-to-end in
# dev (messages print to the server log) without silently failing.
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="WellNest <no-reply@wellnest.health>"
)
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if EMAIL_HOST
        else "django.core.mail.backends.console.EmailBackend"
    ),
)
# Clinic-facing base URL used in reminder emails (links back to the app).
WELLNEST_PUBLIC_BASE_URL = config("WELLNEST_PUBLIC_BASE_URL", default="")
