from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count,F, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from collections import Counter

from Modulos.usuarios.auditoria import registrar
from Modulos.usuarios.models import Auditoria
from django.db.models.functions import Coalesce

from django.core.exceptions import PermissionDenied

from Modulos.facturacion.models import (
    PLAZO_DEVOLUCION_DIAS, PLAZO_GARANTIA_DIAS, Cliente, DetalleDevolucion,
    DetalleFactura, Devolucion, Factura, Garantia, Producto, SeguimientoGarantia,
)

# Create your views here.

def _cop(n):
    """1234567 -> $1.234.567"""
    return '$' + f'{n:,}'.replace(',', '.')


def _fecha(texto):
    try:
        return parse_date((texto or '').strip())
    except ValueError:
        return None


def _entero(texto, minimo=1, maximo=10**9):
    try:
        n = int(texto)
    except (TypeError, ValueError):
        return None
    return n if minimo <= n <= maximo else None

@login_required
@permission_required('facturacion.view_factura', raise_exception=True)
def consulta_facturas(request):
    facturas = Factura.objects.select_related('cliente')

    numero = request.GET.get('numero', '').strip()
    cliente = request.GET.get('cliente', '').strip()
    fecha = request.GET.get('fecha', '').strip()
    estado = request.GET.get('estado', '')

    if numero:
        # Acepta "0001245" o "1245"
        pk = _entero(numero.lstrip('0'), 1, 10**12)
        facturas = facturas.filter(pk=pk) if pk else facturas.none()

    if cliente:
        # Cada palabra debe aparecer en los nombres o en los apellidos
        for palabra in cliente.split():
            facturas = facturas.filter(
                Q(cliente__nombres__icontains=palabra)
                | Q(cliente__apellidos__icontains=palabra)
            )

    if fecha and _fecha(fecha):
        facturas = facturas.filter(fecha_factura=_fecha(fecha))

    if estado in Factura.Estado.values:
        facturas = facturas.filter(estado=estado)

    return render(request, 'consulta_factura.html', {
        'facturas': [{
            'numero': f.numero,
            'cliente': f.cliente.nombre_completo,
            'fecha': f.fecha_factura.strftime('%d/%m/%Y'),
            'total': _cop(f.total),
            'estado': f.get_estado_display(),
            'clase': f.clase,
        } for f in facturas[:200]],
        'estados': Factura.Estado.choices,
        'f': {'numero': numero, 'cliente': cliente, 'fecha': fecha, 'estado': estado},
    })

@login_required
@permission_required('facturacion.add_factura', raise_exception=True)
def nueva_factura(request):
    url = reverse('nueva_factura')
    hoy = timezone.localdate()
    productos = Producto.objects.filter(activo=True)

    if request.method == 'POST':
        nombres = ' '.join(request.POST.get('nombres', '').split())[:100]
        apellidos = ' '.join(request.POST.get('apellidos', '').split())[:100]
        fecha = _fecha(request.POST.get('fecha'))
        errores = []

        if not nombres or not apellidos:
            errores.append('Escribe los nombres y apellidos del cliente.')
        if fecha is None or fecha > hoy:
            errores.append('La fecha no es válida (no puede ser futura).')

        # Se agrupan los productos repetidos: {id_producto: cantidad}
        pedido = {}
        for pid, cant in zip(request.POST.getlist('producto'), request.POST.getlist('cantidad')):
            pid, cant = _entero(pid), _entero(cant, 1, 10000)
            if pid is None or cant is None:
                errores.append('Hay productos o cantidades no válidos.')
                break
            pedido[pid] = pedido.get(pid, 0) + cant
        if not pedido and not errores:
            errores.append('Agrega al menos un producto.')

        # El precio se toma SIEMPRE de la base de datos, nunca del navegador
        encontrados = {p.pk: p for p in productos.filter(pk__in=pedido)}
        if pedido and len(encontrados) != len(pedido):
            errores.append('Alguno de los productos ya no está disponible.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return redirect(url)

        with transaction.atomic():
            cliente = (
                Cliente.objects.filter(nombres__iexact=nombres, apellidos__iexact=apellidos).first()
                or Cliente.objects.create(nombres=nombres, apellidos=apellidos)
            )
            factura = Factura.objects.create(
                fecha_factura=fecha, cliente=cliente, usuario=request.user)

            total = 0
            for pid, cant in pedido.items():
                p = encontrados[pid]
                acumulado = p.precio_venta_unitario * cant
                DetalleFactura.objects.create(
                    factura=factura, producto=p, cantidad=cant, precio_acumulado=acumulado)
                total += acumulado

            factura.total = total
            factura.save(update_fields=['total'])

        registrar(request, Auditoria.Evento.CREACION,
                  f'Factura {factura.numero} de {cliente.nombre_completo} por {_cop(total)}')
        messages.success(request, f'Factura {factura.numero} generada por {_cop(total)}.')
        return redirect(url)

    return render(request, 'fac_nueva.html', {
        # Se renombran las claves para que el HTML y el JS sigan funcionando igual
        'productos': list(
            productos.annotate(nombre=F('nombre_producto'), precio=F('precio_venta_unitario'))
            .values('id', 'codigo', 'nombre', 'precio')
        ),
        'hoy': hoy.isoformat(),
    })
PERIODOS = [
    ('hoy', 'Hoy'),
    ('7dias', 'Últimos 7 días'),
    ('mes', 'Este mes'),
    ('mes_anterior', 'Mes anterior'),
    ('anio', 'Este año'),
    ('todo', 'Todo el historial'),
]


def _rango(periodo):
    """Devuelve (desde, hasta) para el periodo elegido; None = sin límite."""
    hoy = timezone.localdate()
    if periodo == 'hoy':
        return hoy, hoy
    if periodo == '7dias':
        return hoy - timedelta(days=6), hoy
    if periodo == 'mes_anterior':
        hasta = hoy.replace(day=1) - timedelta(days=1)
        return hasta.replace(day=1), hasta
    if periodo == 'anio':
        return date(hoy.year, 1, 1), hoy
    if periodo == 'todo':
        return None, None
    return hoy.replace(day=1), hoy          # 'mes'


@login_required
@permission_required('facturacion.view_factura', raise_exception=True)
def reporte_ventas(request):
    periodo = request.GET.get('periodo', 'mes')
    if periodo not in dict(PERIODOS):
        periodo = 'mes'
    vendedor = request.GET.get('vendedor', '')
    producto = request.GET.get('producto', '')
    desde, hasta = _rango(periodo)

    # Se trabaja sobre las líneas de factura: así el filtro por producto
    # suma solo lo vendido de ese producto. Las facturas anuladas no cuentan.
    lineas = DetalleFactura.objects.exclude(factura__estado=Factura.Estado.ANULADA)
    if desde:
        lineas = lineas.filter(factura__fecha_factura__gte=desde)
    if hasta:
        lineas = lineas.filter(factura__fecha_factura__lte=hasta)
    if _entero(vendedor):
        lineas = lineas.filter(factura__usuario_id=int(vendedor))
    if _entero(producto):
        lineas = lineas.filter(producto_id=int(producto))

    # --- Totales ---
    resumen = lineas.aggregate(total=Sum('precio_acumulado'), ventas=Count('factura', distinct=True))
    total = resumen['total'] or 0
    ventas = resumen['ventas'] or 0

    # --- Tabla por vendedor ---
    filas = (
        lineas.values('factura__usuario__username', 'factura__usuario__empleado__nombre_completo')
        .annotate(ventas=Count('factura', distinct=True), total=Sum('precio_acumulado'))
        .order_by('-total')
    )
    por_vendedor = [{
        'nombre': f['factura__usuario__empleado__nombre_completo'] or f['factura__usuario__username'],
        'ventas': f['ventas'],
        'total': _cop(f['total'] or 0),
    } for f in filas]

    # --- Gráfico: una barra por día (por mes si el rango pasa de ~3 meses) ---
    por_dia = {
        r['factura__fecha_factura']: r['total'] or 0
        for r in lineas.values('factura__fecha_factura').annotate(total=Sum('precio_acumulado'))
    }
    barras = []
    if por_dia:
        ini = desde or min(por_dia)
        fin = hasta or max(por_dia)
        if (fin - ini).days > 92:
            meses = {}
            for d, t in por_dia.items():
                meses[(d.year, d.month)] = meses.get((d.year, d.month), 0) + t
            serie = [(f'{m:02d}/{a}', t) for (a, m), t in sorted(meses.items())]
        else:
            serie, d = [], ini
            while d <= fin:
                serie.append((d.strftime('%d/%m'), por_dia.get(d, 0)))
                d += timedelta(days=1)

        maximo = max(t for _, t in serie) or 1
        paso = max(1, -(-len(serie) // 12))          # máximo ~12 etiquetas visibles
        barras = [{
            'etiqueta': e,
            'texto': _cop(t),
            'alto': max(3, round(t * 100 / maximo)) if t else 0,
            'mostrar': i % paso == 0,
        } for i, (e, t) in enumerate(serie)]

    # --- Listas de los filtros ---
    vendedores = [
        {'id': u.pk, 'nombre': u.empleado.nombre_completo if u.empleado else u.get_username()}
        for u in get_user_model().objects.filter(facturas__isnull=False)
        .select_related('empleado').distinct().order_by('username')
    ]

    return render(request, 'reporte_ventas.html', {
        'periodos': PERIODOS, 'periodo': periodo,
        'vendedor': vendedor, 'producto': producto,
        'vendedores': vendedores,
        'productos': Producto.objects.all(),
        'por_vendedor': por_vendedor,
        'barras': barras,
        'total': _cop(total),
        'ventas': ventas,
        'promedio': _cop(total // ventas if ventas else 0),
    })


def _buscar_factura(texto):
    """Busca una factura por número: acepta '0001245' o '1245'."""
    pk = _entero((texto or '').strip().lstrip('0'), 1, 10**12)
    return Factura.objects.select_related('cliente').filter(pk=pk).first() if pk else None


def _lineas_factura(factura):
    """Productos de la factura con lo ya devuelto y lo que todavía se puede devolver."""
    detalles = (
        factura.detalles.select_related('producto')
        .annotate(devuelto=Coalesce(Sum('lineas_devueltas__cantidad'), 0))
        .order_by('pk')
    )
    return [{
        'detalle': d,
        'comprado': d.cantidad,
        'devuelto': d.devuelto,
        'disponible': max(0, d.cantidad - d.devuelto),
    } for d in detalles]


def _problemas_devolucion(factura, lineas):
    problemas = []
    if factura.estado == Factura.Estado.ANULADA:
        problemas.append('La factura está anulada.')
    dias = (timezone.localdate() - factura.fecha_factura).days
    if dias > PLAZO_DEVOLUCION_DIAS:
        problemas.append(
            f'El plazo para devolver ({PLAZO_DEVOLUCION_DIAS} días) ya venció: '
            f'la compra fue hace {dias} días.')
    if not any(l['disponible'] for l in lineas):
        problemas.append('Todos los productos de esta factura ya fueron devueltos.')
    return problemas


@login_required
@permission_required('facturacion.add_devolucion', raise_exception=True)
def registrar_devolucion(request):
    url = reverse('registrar_devolucion')
    datos = request.POST if request.method == 'POST' else request.GET
    texto = datos.get('factura', '').strip()
    factura = _buscar_factura(texto) if texto else None

    if texto and factura is None:
        messages.error(request, f'No existe la factura "{texto}".')

    lineas, problemas = [], []
    if factura:
        lineas = _lineas_factura(factura)
        problemas = _problemas_devolucion(factura, lineas)

    if request.method == 'POST' and factura:
        back = f'{url}?factura={factura.numero}'

        if problemas:
            for p in problemas:
                messages.error(request, p)
            return redirect(back)

        errores = []
        motivo = request.POST.get('motivo', '')
        resolucion = request.POST.get('tipo_resolucion', '')
        if motivo not in Devolucion.Motivo.values:
            errores.append('Selecciona el motivo de la devolución.')
        if resolucion not in Devolucion.Resolucion.values:
            errores.append('Selecciona cómo se resolverá la devolución.')
        if request.POST.get('etiquetas') != 'on':
            errores.append('Confirma que el producto conserva las etiquetas intactas.')

        # Productos marcados y su cantidad (nunca más de lo disponible)
        elegidos = set(request.POST.getlist('detalle'))
        a_devolver = []
        for l in lineas:
            pk = str(l['detalle'].pk)
            if pk not in elegidos:
                continue
            cant = _entero(request.POST.get(f'cantidad_{pk}'), 1, l['disponible'] or 0)
            if cant is None:
                errores.append(
                    f'Cantidad no válida para «{l["detalle"].producto.nombre_producto}» '
                    f'(máximo {l["disponible"]}).')
            else:
                a_devolver.append((l['detalle'], cant))
        if not a_devolver and not errores:
            errores.append('Selecciona al menos un producto a devolver.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return redirect(back)

        with transaction.atomic():
            devolucion = Devolucion.objects.create(
                factura=factura, motivo=motivo,
                tipo_resolucion=resolucion, usuario=request.user)
            for detalle, cant in a_devolver:
                DetalleDevolucion.objects.create(
                    devolucion=devolucion, detalle_factura=detalle, cantidad=cant)

        # Valor de lo devuelto = precio acumulado proporcional a la cantidad
        valor = sum(d.precio_acumulado * c // d.cantidad for d, c in a_devolver)
        registrar(request, Auditoria.Evento.CREACION,
                  f'Devolución {devolucion.numero} de la factura {factura.numero} '
                  f'({devolucion.get_motivo_display()})')
        messages.success(
            request,
            f'Devolución {devolucion.numero} registrada. Valor de los productos: {_cop(valor)}.')
        return redirect(url)

    return render(request, 'devolucion.html', {
        'texto': texto,
        'factura': factura,
        'factura_total': _cop(factura.total) if factura else '',
        'lineas': lineas,
        'problemas': problemas,
        'motivos': Devolucion.Motivo.choices,
        'resoluciones': Devolucion.Resolucion.choices,
        'plazo': PLAZO_DEVOLUCION_DIAS,
    })


ESTADOS_ABIERTOS = [
    Garantia.Estado.SOLICITADA, Garantia.Estado.TRAMITE, Garantia.Estado.APROBADA,
]


def _problemas_garantia(factura):
    problemas = []
    if factura.estado == Factura.Estado.ANULADA:
        problemas.append('La factura está anulada.')
    dias = (timezone.localdate() - factura.fecha_factura).days
    if dias > PLAZO_GARANTIA_DIAS:
        problemas.append(
            f'El plazo para solicitar garantía ({PLAZO_GARANTIA_DIAS} días) ya venció: '
            f'la compra fue hace {dias} días.')
    return problemas


@login_required
@permission_required('facturacion.add_garantia', raise_exception=True)
def solicitud_garantia(request):

    u = request.user
    puede_crear = u.has_perm('facturacion.add_garantia')
    puede_tramitar = u.has_perm('facturacion.seguimiento_garantia')
    puede_decidir = u.has_perm('facturacion.aprobar_garantia')
    if not (puede_crear or puede_tramitar or puede_decidir):
        raise PermissionDenied

    url = reverse('solicitud_garantia')

    if request.method == 'POST':
        accion = request.POST.get('accion', '')

        # ---------- Vendedor: crear la solicitud ----------
        if accion == 'crear':
            if not puede_crear:
                raise PermissionDenied

            factura = _buscar_factura(request.POST.get('factura'))
            if factura is None:
                messages.error(request, 'La factura no existe.')
                return redirect(url)
            back = f'{url}?factura={factura.numero}'

            detalle = factura.detalles.select_related('producto').filter(
                pk=_entero(request.POST.get('detalle'))).first()
            descripcion = request.POST.get('descripcion', '').strip()[:1000]

            errores = _problemas_garantia(factura)
            if detalle is None:
                errores.append('Selecciona un producto de la factura.')
            elif Garantia.objects.filter(
                    detalle_factura=detalle, estado__in=ESTADOS_ABIERTOS).exists():
                errores.append('Ese producto ya tiene una garantía en curso.')
            if not descripcion:
                errores.append('Describe la falla del producto.')

            if errores:
                for e in errores:
                    messages.error(request, e)
                return redirect(back)

            garantia = Garantia.objects.create(
                detalle_factura=detalle, descripcion=descripcion, usuario_vendedor=u)
            registrar(request, Auditoria.Evento.CREACION,
                      f'Garantía {garantia.numero}: {detalle.producto.nombre_producto} '
                      f'(factura {factura.numero})')
            messages.success(request, f'Solicitud {garantia.numero} creada.')
            return redirect(url)

        # ---------- Auxiliar y gerente: cambiar el estado ----------
        if accion in ('tramite', 'repuesta', 'aprobar', 'rechazar'):
            garantia = Garantia.objects.filter(pk=_entero(request.POST.get('garantia'))).first()
            Estado = Garantia.Estado

            if garantia is None:
                messages.error(request, 'La solicitud no existe.')
                return redirect(url)

            if accion in ('tramite', 'repuesta'):
                if not puede_tramitar:
                    raise PermissionDenied
                esperado, nuevo = (
                    (Estado.SOLICITADA, Estado.TRAMITE) if accion == 'tramite'
                    else (Estado.APROBADA, Estado.REPUESTA)
                )
                if garantia.estado != esperado:
                    messages.error(request, f'{garantia.numero} ya no está en estado "{Estado(esperado).label}".')
                    return redirect(url)
                with transaction.atomic():
                    garantia.estado = nuevo
                    campos = ['estado']
                    if nuevo == Estado.REPUESTA:
                        garantia.fecha_reposicion = timezone.now()
                        campos.append('fecha_reposicion')
                    garantia.save(update_fields=campos)
                    SeguimientoGarantia.objects.create(
                        garantia=garantia, usuario_auxiliar=u, estado=nuevo)
            else:
                if not puede_decidir:
                    raise PermissionDenied
                if garantia.estado not in (Estado.SOLICITADA, Estado.TRAMITE):
                    messages.error(request, f'{garantia.numero} ya fue resuelta.')
                    return redirect(url)
                garantia.estado = Estado.APROBADA if accion == 'aprobar' else Estado.RECHAZADA
                garantia.usuario_gerente = u
                garantia.fecha_decision = timezone.now()
                garantia.save(update_fields=['estado', 'usuario_gerente', 'fecha_decision'])

            messages.success(request, f'{garantia.numero}: {garantia.get_estado_display().lower()}.')
            return redirect(url)

        return redirect(url)

    # ---------- Mostrar ----------
    texto = request.GET.get('factura', '').strip()
    factura, detalles, problemas = None, [], []
    if texto and puede_crear:
        factura = _buscar_factura(texto)
        if factura is None:
            messages.error(request, f'No existe la factura "{texto}".')
        else:
            detalles = list(factura.detalles.select_related('producto').order_by('pk'))
            problemas = _problemas_garantia(factura)

    Estado = Garantia.Estado
    garantias = Garantia.objects.select_related(
        'detalle_factura__producto', 'detalle_factura__factura', 'usuario_vendedor')[:30]
    filas = [{
        'g': g,
        'tramitar': puede_tramitar and g.estado == Estado.SOLICITADA,
        'reponer': puede_tramitar and g.estado == Estado.APROBADA,
        'decidir': puede_decidir and g.estado in (Estado.SOLICITADA, Estado.TRAMITE),
    } for g in garantias]

    return render(request, 'garantia.html', {
        'puede_crear': puede_crear,
        'texto': texto, 'factura': factura, 'detalles': detalles, 'problemas': problemas,
        'plazo': PLAZO_GARANTIA_DIAS,
        'filas': filas,
    })


@login_required
@permission_required('facturacion.view_devolucion', raise_exception=True)
def reporte_dg(request):
    periodo = request.GET.get('periodo', 'mes')
    if periodo not in dict(PERIODOS):
        periodo = 'mes'
    producto = request.GET.get('producto', '')
    motivo = request.GET.get('motivo', '')
    agrupar = request.GET.get('agrupar', 'producto')
    if agrupar not in ('producto', 'cliente', 'mes'):
        agrupar = 'producto'
    desde, hasta = _rango(periodo)

    devs = DetalleDevolucion.objects.select_related(
        'devolucion', 'detalle_factura__producto', 'detalle_factura__factura__cliente')
    gars = Garantia.objects.select_related(
        'detalle_factura__producto', 'detalle_factura__factura__cliente')

    if desde:
        devs = devs.filter(devolucion__fecha_devolucion__date__gte=desde)
        gars = gars.filter(fecha_solicitud__date__gte=desde)
    if hasta:
        devs = devs.filter(devolucion__fecha_devolucion__date__lte=hasta)
        gars = gars.filter(fecha_solicitud__date__lte=hasta)
    if _entero(producto):
        devs = devs.filter(detalle_factura__producto_id=int(producto))
        gars = gars.filter(detalle_factura__producto_id=int(producto))

    # El motivo solo existe en las devoluciones: al filtrarlo, las garantías quedan fuera
    if motivo in Devolucion.Motivo.values:
        devs = devs.filter(devolucion__motivo=motivo)
        gars = gars.none()
    else:
        motivo = ''

    def clave(detalle, fecha):
        if agrupar == 'producto':
            return f'{detalle.producto.codigo} · {detalle.producto.nombre_producto}'
        if agrupar == 'cliente':
            return detalle.factura.cliente.nombre_completo
        return timezone.localtime(fecha).strftime('%Y-%m')

    grupos = {}

    def grupo(k):
        return grupos.setdefault(k, {'dev': 0, 'gar': 0, 'motivos': Counter()})

    for l in devs:
        g = grupo(clave(l.detalle_factura, l.devolucion.fecha_devolucion))
        g['dev'] += 1
        g['motivos'][l.devolucion.get_motivo_display()] += 1
    for gr in gars:
        grupo(clave(gr.detalle_factura, gr.fecha_solicitud))['gar'] += 1

    filas = []
    for nombre, g in grupos.items():
        top = sorted(g['motivos'].items(), key=lambda kv: (-kv[1], kv[0]))
        filas.append({
            'grupo': nombre,
            'devoluciones': g['dev'],
            'garantias': g['gar'],
            'motivo': top[0][0] if top else '—',
        })

    if agrupar == 'mes':
        filas.sort(key=lambda f: f['grupo'], reverse=True)
    else:
        filas.sort(key=lambda f: (-(f['devoluciones'] + f['garantias']), f['grupo']))

    return render(request, 'reporte_dg.html', {
        'periodos': PERIODOS, 'periodo': periodo,
        'producto': producto, 'motivo': motivo, 'agrupar': agrupar,
        'productos': Producto.objects.all(),
        'motivos': Devolucion.Motivo.choices,
        'filas': filas,
        'total_dev': sum(f['devoluciones'] for f in filas),
        'total_gar': sum(f['garantias'] for f in filas),
        'titulo_grupo': {'producto': 'Producto', 'cliente': 'Clienta', 'mes': 'Mes'}[agrupar],
    })