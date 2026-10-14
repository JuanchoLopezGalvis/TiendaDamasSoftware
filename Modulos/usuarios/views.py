from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from itertools import groupby
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.utils.crypto import get_random_string

from Modulos.usuarios.models import Empleado, Usuario, Auditoria
from Modulos.usuarios.auditoria import registrar
from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.core.exceptions import PermissionDenied
from django.utils.dateparse import parse_date
# Create your views here.
ACCIONES = {
    'add': 'Agregar',
    'change': 'Modificar',
    'delete': 'Eliminar',
    'view': 'Ver',
}

def nombre_permiso(p):
    """Devuelve el nombre del permiso en español."""
    accion = p.codename.split('_', 1)[0]
    modelo = p.content_type.model_class()
    if (
        accion in ACCIONES
        and modelo is not None
        and p.codename == f'{accion}_{modelo._meta.model_name}'
    ):
        return f'{ACCIONES[accion]} {modelo._meta.verbose_name}'
    return p.name

@login_required
def panel(request):
    usuario = request.user
    roles = usuario.groups.order_by('name')
    permisos = sorted(
        {nombre_permiso(p) for p in Permission.objects.filter(
            group__user=usuario
        ).select_related('content_type')}
    )
    return render(request, 'perfil.html', {
        'roles': roles,
        'permisos': permisos,
    })

@login_required
def perfil(request):
    usuario = request.user
    roles = usuario.groups.order_by('name')
    permisos = sorted(
        {nombre_permiso(p) for p in Permission.objects.filter(
            group__user=usuario
        ).select_related('content_type')}
    )
    return render(request, 'perfil.html', {
        'roles': roles,
        'permisos': permisos,
    })

def _seccion(request, titulo, descripcion):
    return render(request, 'seccion.html', {
        'titulo': titulo,
        'descripcion': descripcion,
    })
@login_required
@permission_required('usuarios.add_empleado', raise_exception=True)
def crear_empleado(request):
    url = reverse('crear_empleado')
    valores = {'documento': '', 'nombre': ''}

    if request.method == 'POST':
        documento = request.POST.get('documento', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        valores = {'documento': documento, 'nombre': nombre}

        if not documento or not nombre:
            messages.error(request, 'Completa el documento y el nombre.')
        elif len(documento) > 50 or len(nombre) > 50:
            messages.error(request, 'El documento y el nombre admiten máximo 50 caracteres.')
        elif Empleado.objects.filter(pk=documento).exists():
            messages.error(request, 'Ya existe un empleado con ese documento.')
        else:
            Empleado.objects.create(documento_identidad=documento, nombre_completo=nombre)
            registrar(request, Auditoria.Evento.CREACION, f'Empleado {nombre} ({documento})')
            messages.success(request, f'Empleado "{nombre}" registrado.')
            return redirect(url)

    return render(request, 'empleados.html', {'valores': valores})

@login_required
@permission_required('usuarios.add_usuario', raise_exception=True)
def registro_usuario(request):
    empleados = Empleado.objects.filter(usuario__isnull=True).order_by('nombre_completo')
    grupos = Group.objects.order_by('name')
    datos = {}

    if request.method == 'POST':
        datos = request.POST
        username = datos.get('username', '').strip()
        correo = datos.get('correo', '').strip()
        empleado = empleados.filter(pk=datos.get('empleado')).first()
        rol_id = datos.get('rol', '')
        grupo = grupos.filter(pk=rol_id).first() if rol_id.isdigit() else None

        errores = []
        if empleado is None:
            errores.append('Selecciona un empleado de la lista.')
        if not username:
            errores.append('Escribe el nombre de usuario.')
        elif Usuario.objects.filter(username__iexact=username).exists():
            errores.append('Ese nombre de usuario ya está en uso.')
        try:
            validate_email(correo)
        except ValidationError:
            errores.append('Escribe un correo válido.')
        if grupo is None:
            errores.append('Selecciona un rol.')

        if not errores:
            clave = get_random_string(12)
            usuario = Usuario.objects.create_user(
                username=username,
                email=correo,
                password=clave,
                empleado=empleado,
            )
            usuario.groups.add(grupo)
            registrar(request, Auditoria.Evento.CREACION, f'Usuario {username} con rol {grupo.name}')

            try:
                send_mail(
                    'Tu cuenta en TiendaDamas',
                    f'Hola {empleado.nombre_completo},\n\n'
                    f'Se creó tu cuenta.\n'
                    f'Usuario: {username}\n'
                    f'Contraseña temporal: {clave}\n\n'
                    f'Cámbiala en tu primer ingreso.',
                    None,
                    [correo],
                )
                messages.success(
                    request,
                    f'Cuenta creada para {empleado.nombre_completo}. '
                    f'La contraseña temporal se envió a {correo}.')
            except Exception:
                messages.warning(
                    request,
                    'La cuenta se creó, pero no se pudo enviar el correo.')
            return redirect('registro_usuario')

        for e in errores:
            messages.error(request, e)

    return render(request, 'signup.html', {
        'empleados': empleados,
        'grupos': grupos,
        'datos': datos,
    })

@login_required
def consulta(request):
    puede_empleados = request.user.has_perm('usuarios.view_empleado')
    puede_usuarios = request.user.has_perm('usuarios.view_usuario')
    if not (puede_empleados or puede_usuarios):
        raise PermissionDenied

    tipo = request.GET.get('tipo', 'empleados')
    if tipo == 'usuarios' and not puede_usuarios:
        tipo = 'empleados'
    if tipo == 'empleados' and not puede_empleados:
        tipo = 'usuarios'

    buscar = request.GET.get('buscar', '').strip()

    if tipo == 'empleados':
        resultados = Empleado.objects.order_by('nombre_completo')
        if buscar:
            resultados = resultados.filter(
                Q(nombre_completo__icontains=buscar)
                | Q(documento_identidad__icontains=buscar)
            )
    else:
        resultados = (
            Usuario.objects
            .select_related('empleado')
            .prefetch_related('groups')
            .order_by('username')
        )
        if buscar:
            resultados = resultados.filter(
                Q(username__icontains=buscar)
                | Q(email__icontains=buscar)
                | Q(empleado__nombre_completo__icontains=buscar)
            )

    return render(request, 'consulta.html', {
        'tipo': tipo,
        'buscar': buscar,
        'resultados': resultados,
        'puede_empleados': puede_empleados,
        'puede_usuarios': puede_usuarios,
    })

@login_required
def roles_permisos(request):
    url = reverse('roles_permisos')

    # ---------- Acciones (POST) ----------
    if request.method == 'POST':
        if 'eliminar' in request.POST:
            if not request.user.has_perm('auth.delete_group'):
                raise PermissionDenied
            grupo = get_object_or_404(Group, pk=request.POST.get('rol'))
            asignados = grupo.user_set.count()
            if asignados:
                messages.error(
                    request,
                    f'No se puede eliminar "{grupo.name}": tiene {asignados} '
                    f'usuario(s) asignado(s). Cámbiales el rol primero.')
                return redirect(f'{url}?rol={grupo.pk}')
            nombre = grupo.name
            grupo.delete()
            registrar(request, Auditoria.Evento.CAMBIO_ROL, f'Rol {nombre} eliminado')
            messages.success(request, f'Rol "{nombre}" eliminado.')
            return redirect(url)
        accion = request.POST.get('accion')

        if accion == 'nuevo':
            if not request.user.has_perm('auth.add_group'):
                raise PermissionDenied
            nombre = request.POST.get('nombre', '').strip()
            if not nombre:
                messages.error(request, 'Escribe un nombre para el nuevo rol.')
            elif Group.objects.filter(name__iexact=nombre).exists():
                messages.error(request, 'Ya existe un rol con ese nombre.')
            else:
                grupo = Group.objects.create(name=nombre)
                registrar(request, Auditoria.Evento.CREACION, f'Rol {grupo.name}')
                messages.success(request, f'Rol "{grupo.name}" creado.')
                return redirect(f'{url}?rol={grupo.pk}')
            return redirect(url)

        if accion == 'guardar':
            if not request.user.has_perm('auth.change_group'):
                raise PermissionDenied
            grupo = get_object_or_404(Group, pk=request.POST.get('rol'))
            ids = request.POST.getlist('permisos')
            grupo.permissions.set(Permission.objects.filter(pk__in=ids))
            registrar(request, Auditoria.Evento.CAMBIO_ROL, f'Permisos del rol {grupo.name} actualizados')
            messages.success(request, f'Permisos del rol "{grupo.name}" actualizados.')
            return redirect(f'{url}?rol={grupo.pk}')

        return redirect(url)

    # ---------- Mostrar (GET) ----------
    grupos = Group.objects.annotate(num_usuarios=Count('user')).order_by('name')

    seleccionado = None
    rol_id = request.GET.get('rol')
    if rol_id and rol_id.isdigit():
        seleccionado = grupos.filter(pk=rol_id).first()
    if seleccionado is None:
        seleccionado = grupos.first()

    marcados = set()
    if seleccionado:
        marcados = set(seleccionado.permissions.values_list('pk', flat=True))

    permisos = Permission.objects.select_related('content_type').order_by(
        'content_type__app_label', 'content_type__model', 'codename'
    )
    # Agrupados por modelo: "usuarios | usuario", "auth | grupo", etc.
    bloques = []
    for ct, items in groupby(permisos, key=lambda p: p.content_type):
        lista = list(items)
        for p in lista:
            p.nombre_es = nombre_permiso(p)
        bloques.append({'titulo': str(ct), 'permisos': lista})

    return render(request, 'roles.html', {
        'grupos': grupos,
        'seleccionado': seleccionado,
        'marcados': marcados,
        'bloques': bloques,
    })
@login_required
@permission_required('usuarios.change_usuario', raise_exception=True)
def asignacion_roles(request):
    url = reverse('asignacion_roles')

    # ---------- Acciones (POST) ----------
    if request.method == 'POST':
        accion = request.POST.get('accion')
        uid = request.POST.get('usuario', '')

        if not uid.isdigit():
            messages.error(request, 'Usuario no válido.')
            return redirect(url)

        usuario = get_object_or_404(Usuario, pk=uid)
        nombre = usuario.get_username()

        if accion == 'asignar':
            rol_id = request.POST.get('rol', '')
            if rol_id == '':
                usuario.groups.clear()
                registrar(request, Auditoria.Evento.CAMBIO_ROL, f'Se quitó el rol a {nombre}')
                messages.success(request, f'Se quitó el rol a "{nombre}".')
            elif rol_id.isdigit():
                grupo = get_object_or_404(Group, pk=rol_id)
                usuario.groups.set([grupo])
                registrar(request, Auditoria.Evento.CAMBIO_ROL, f'{nombre} ahora tiene el rol {grupo.name}')
                messages.success(request, f'"{nombre}" ahora tiene el rol "{grupo.name}".')
            else:
                messages.error(request, 'Rol no válido.')

        elif accion == 'estado':
            if usuario.pk == request.user.pk:
                messages.error(request, 'No puedes desactivar tu propia cuenta.')
            else:
                usuario.is_active = not usuario.is_active
                usuario.save(update_fields=['is_active'])
                estado = 'activada' if usuario.is_active else 'desactivada'
                messages.success(request, f'Cuenta de "{nombre}" {estado}.')

        return redirect(url)

    # ---------- Mostrar (GET) ----------
    buscar = request.GET.get('buscar', '').strip()
    estado = request.GET.get('estado', '')

    usuarios = (
        Usuario.objects
        .select_related('empleado')
        .prefetch_related('groups')
        .order_by('username')
    )

    if buscar:
        usuarios = usuarios.filter(
            Q(username__icontains=buscar)
            | Q(first_name__icontains=buscar)
            | Q(last_name__icontains=buscar)
            | Q(empleado__nombre_completo__icontains=buscar)
        )
    if estado == 'activo':
        usuarios = usuarios.filter(is_active=True)
    elif estado == 'inactivo':
        usuarios = usuarios.filter(is_active=False)

    return render(request, 'asignacion.html', {
        'usuarios': usuarios,
        'grupos': Group.objects.order_by('name'),
        'buscar': buscar,
        'estado': estado,
    })


def _fecha(texto):
    try:
        return parse_date(texto) if texto else None
    except ValueError:
        return None


@login_required
@permission_required('usuarios.view_auditoria', raise_exception=True)
def bitacora_auditoria(request):
    desde = request.GET.get('desde', '')
    hasta = request.GET.get('hasta', '')
    tipo = request.GET.get('tipo', '')

    registros = Auditoria.objects.select_related('usuario')
    if _fecha(desde):
        registros = registros.filter(fecha__date__gte=_fecha(desde))
    if _fecha(hasta):
        registros = registros.filter(fecha__date__lte=_fecha(hasta))
    if tipo in Auditoria.Evento.values:
        registros = registros.filter(evento=tipo)

    return render(request, 'bitacora.html', {
        'registros': registros[:200],
        'total': registros.count(),
        'eventos': Auditoria.Evento.choices,
        'desde': desde,
        'hasta': hasta,
        'tipo': tipo,
    })

class CambiarClaveView(SuccessMessageMixin, PasswordChangeView):
    template_name = 'cambiar_clave.html'
    success_url = reverse_lazy('cambiar_clave')
    success_message = 'Tu contraseña se actualizó correctamente.'


def recuperar_clave(request):
    username = ''

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        documento = request.POST.get('documento', '').strip()

        usuario = Usuario.objects.filter(
            username__iexact=username,
            empleado__documento_identidad=documento,
            is_active=True,
        ).first()

        if usuario and usuario.email:
            clave = get_random_string(12)
            usuario.set_password(clave)
            usuario.save(update_fields=['password'])
            try:
                send_mail(
                    'Recuperación de contraseña - TiendaDamas',
                    f'Hola {usuario.empleado.nombre_completo},\n\n'
                    f'Tu contraseña temporal es: {clave}\n\n'
                    f'Cámbiala en tu próximo ingreso.',
                    None,
                    [usuario.email],
                )
            except Exception:
                pass

        # Mismo mensaje exista o no el usuario, para no revelar qué cuentas existen
        messages.success(
            request,
            'Si los datos son correctos, enviamos una contraseña temporal al correo registrado.'
        )
        return redirect('login')

    return render(request, 'recuperar_clave.html', {'username': username})