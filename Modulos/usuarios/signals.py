from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from Modulos.usuarios.auditoria import registrar
from Modulos.usuarios.models import Auditoria


@receiver(user_logged_in)
def login_exitoso(sender, request, user, **kwargs):
    registrar(request, Auditoria.Evento.INICIO_SESION, 'Exitoso', usuario=user)


@receiver(user_login_failed)
def login_fallido(sender, credentials, request=None, **kwargs):
    nombre = credentials.get('username', '')
    registrar(
        request,
        Auditoria.Evento.ACCESO_DENEGADO,
        'Credenciales incorrectas',
        usuario_texto=nombre or 'Desconocido',
    )


@receiver(user_logged_out)
def cierre_sesion(sender, request, user, **kwargs):
    if user is not None:
        registrar(request, Auditoria.Evento.CIERRE_SESION, 'Cerró sesión', usuario=user)
