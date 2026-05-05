from .settings import *
import os

# Production overrides
DEBUG = False

SECRET_KEY = os.environ.get("SECRET_KEY")

ALLOWED_HOSTS = [
    "wellnestscribe.com",
    "www.wellnestscribe.com",
    os.environ.get("WEBSITE_HOSTNAME", ""),  # Azure sets this automatically
    "169.254.129.2",  # Azure internal health probe IP from your logs
    "localhost",
    "127.0.0.1",
]
ALLOWED_HOSTS = [h for h in ALLOWED_HOSTS if h]  # remove empty strings

CSRF_TRUSTED_ORIGINS = [
    "https://wellnestscribe.com",
    "https://www.wellnestscribe.com",
    f"https://{os.environ.get('WEBSITE_HOSTNAME', '')}",
]

# Whitenoise for static files
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

STATIC_ROOT = BASE_DIR / "staticfiles"

# Azure proxy SSL
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# MySQL for production
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("AZURE_MYSQL_NAME"),
        "USER": os.environ.get("AZURE_MYSQL_USER"),
        "PASSWORD": os.environ.get("AZURE_MYSQL_PASSWORD"),
        "HOST": os.environ.get("AZURE_MYSQL_HOST"),
        "PORT": os.environ.get("AZURE_MYSQL_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    }
}
