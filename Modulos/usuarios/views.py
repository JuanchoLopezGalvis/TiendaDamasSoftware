from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
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
    return render(request, 'panel.html')


def _seccion(request, titulo, descripcion):
    return render(request, 'seccion.html', {
        'titulo': titulo,
        'descripcion': descripcion,
    })


@login_required
def registro_usuario(request):
    return render(request, 'signup.html')


@login_required
def roles_permisos(request):
    url = reverse('roles_permisos')

    # ---------- Acciones (POST) ----------
    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'nuevo':
            nombre = request.POST.get('nombre', '').strip()
            if not nombre:
                messages.error(request, 'Escribe un nombre para el nuevo rol.')
            elif Group.objects.filter(name__iexact=nombre).exists():
                messages.error(request, 'Ya existe un rol con ese nombre.')
            else:
                grupo = Group.objects.create(name=nombre)
                messages.success(request, f'Rol "{grupo.name}" creado.')
                return redirect(f'{url}?rol={grupo.pk}')
            return redirect(url)

        if accion == 'guardar':
            grupo = get_object_or_404(Group, pk=request.POST.get('rol'))
            ids = request.POST.getlist('permisos')
            grupo.permissions.set(Permission.objects.filter(pk__in=ids))
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
def asignacion_roles(request):
    return render(request, 'asignacion.html')


@login_required
def bitacora_auditoria(request):
    return render(request, 'bitacora.html')