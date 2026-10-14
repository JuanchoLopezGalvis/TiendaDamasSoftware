from Modulos.usuarios.models import Auditoria


def ip_de(request):
    if request is None:
        return None
    return request.META.get('REMOTE_ADDR')


def registrar(request, evento, detalle='', usuario=None, usuario_texto=''):
    """Guarda una fila en la bitácora."""
    if usuario is None and request is not None and request.user.is_authenticated:
        usuario = request.user
    if usuario is not None and not usuario_texto:
        usuario_texto = usuario.get_username()

    Auditoria.objects.create(
        usuario=usuario,
        usuario_texto=usuario_texto[:150],
        evento=evento,
        detalle=detalle[:255],
        ip=ip_de(request),
    )