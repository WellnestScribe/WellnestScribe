"""Django settings for the WellNest Scribe project."""

import sys
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "apps"))

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-change-me-in-production-please-im-begging-you",
)
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,0.0.0.0",
    cast=Csv(),
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "scribe",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

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
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8h max session lifetime
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True  # rolling expiry on activity
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

# ---- WellNest Scribe AI configuration ----
SCRIBE_USE_REAL_AI = config("SCRIBE_USE_REAL_AI", default=False, cast=bool)
SCRIBE_PIPELINE_MODE = config("SCRIBE_PIPELINE_MODE", default="single")  # single | modular
SCRIBE_VERIFIER_ENABLED = config("SCRIBE_VERIFIER_ENABLED", default=False, cast=bool)
SCRIBE_MAX_COMPLETION_TOKENS = config(
    "SCRIBE_MAX_COMPLETION_TOKENS", default=1400, cast=int
)

# Transcription is OpenAI direct (gpt-4o(-mini)-transcribe).
SCRIBE_OPENAI_API_KEY = config("SCRIBE_OPENAI_API_KEY", default="")
SCRIBE_OPENAI_TRANSCRIBE_MODEL = config(
    "SCRIBE_OPENAI_TRANSCRIBE_MODEL", default="gpt-4o-transcribe"
)

# SOAP generation is Azure OpenAI deployment.
SCRIBE_AZURE_OPENAI_ENDPOINT = config("SCRIBE_AZURE_OPENAI_ENDPOINT", default="")
SCRIBE_AZURE_OPENAI_KEY = config("SCRIBE_AZURE_OPENAI_KEY", default="")
SCRIBE_AZURE_OPENAI_DEPLOYMENT = config(
    "SCRIBE_AZURE_OPENAI_DEPLOYMENT", default="gpt-4o-mini"
)
SCRIBE_AZURE_OPENAI_API_VERSION = config(
    "SCRIBE_AZURE_OPENAI_API_VERSION", default="2024-12-01-preview"
)

SCRIBE_MODE = config("SCRIBE_MODE", default="cloud")
PILOT_MODE = config("PILOT_MODE", default=True, cast=bool)
AUTO_DELETE_AUDIO_DAYS = config("AUTO_DELETE_AUDIO_DAYS", default=30, cast=int)

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
