from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Modulos.usuarios'

    def ready(self):
        from Modulos.usuarios import signals  # noqa: F401

