from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        # Wire security signals (failed logins → SecurityEvent) once apps load.
        # Never let signal wiring take down startup (e.g. a mid-reload import race).
        try:
            from . import signals  # noqa: F401
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("accounts signal wiring failed")
