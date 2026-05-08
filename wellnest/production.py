from .settings import *
import os
import socket

from decouple import config as env
import certifi

# Production overrides
DEBUG = False
SECRET_KEY = env("SECRET_KEY", default=SECRET_KEY)

# Build allowed hosts
ALLOWED_HOSTS = [
    "wellnestscribe.com",
    "www.wellnestscribe.com",  # fixed - removed markdown link formatting
    env("WEBSITE_HOSTNAME", default=""),
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
    f"https://{env('WEBSITE_HOSTNAME', default='')}",
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
        "NAME": env("AZURE_MYSQL_NAME", default=""),
        "USER": env("AZURE_MYSQL_USER", default=""),
        "PASSWORD": env("AZURE_MYSQL_PASSWORD", default=""),
        "HOST": env("AZURE_MYSQL_HOST", default=""),
        "PORT": env("AZURE_MYSQL_PORT", default="3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "ssl": {"ca": certifi.where()},  # required for Azure MySQL SSL
        },
        "CONN_MAX_AGE": 60,  # connection pooling - prevents dropped connections
    }
}
