from django.core.exceptions import PermissionDenied

from Modulos.usuarios.auditoria import registrar
from Modulos.usuarios.models import Auditoria


class AuditarAccesoDenegado:
    """Registra en la bitácora cada vez que alguien entra a algo sin permiso (error 403)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, PermissionDenied):
            registrar(request, Auditoria.Evento.ACCESO_DENEGADO,
                      f'Sin permiso para {request.method} {request.path}')
        return None      # Django sigue y muestra la página 403 normal
