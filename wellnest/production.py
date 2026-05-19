from .settings import *
import socket
from .settings import _database_from_env

from decouple import Csv, config as env

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
    ".ngrok-free.app",
]
ALLOWED_HOSTS.extend(env("ALLOWED_HOSTS", default="", cast=Csv()))

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
    "https://*.ngrok-free.app",
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

# MySQL / SQLite / DATABASE_URL are resolved in the shared settings helper so
# production can honor the same SSL env vars as local and App Service.
DATABASES = {"default": _database_from_env()}
