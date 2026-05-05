from .settings import *
import os
import socket

# Production overrides
DEBUG = False
SECRET_KEY = os.environ.get("SECRET_KEY")

# Build allowed hosts
ALLOWED_HOSTS = [
    "wellnestscribe.com",
    "www.wellnestscribe.com",  # fixed - removed markdown link formatting
    os.environ.get("WEBSITE_HOSTNAME", ""),
    "localhost",
    "127.0.0.1",
]

# Dynamically add Azure internal health probe IP
try:
    ALLOWED_HOSTS.append(socket.gethostname())
    ALLOWED_HOSTS.append(socket.gethostbyname(socket.gethostname()))
except Exception:
    pass

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
            "ssl": {"ca": "/etc/ssl/certs/ca-certificates.crt"},  # required for Azure MySQL SSL
        },
        "CONN_MAX_AGE": 60,  # connection pooling - prevents dropped connections
    }
}
