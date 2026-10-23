from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count,F, OuterRef, Q, Subquery, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from collections import Counter
import re
from urllib.parse import urlencode

from Modulos.usuarios.auditoria import registrar
from Modulos.usuarios.models import Auditoria
from django.db.models.functions import Coalesce

from django.core.exceptions import PermissionDenied

from Modulos.facturacion import pdf
from Modulos.facturacion.models import (
    PLAZO_DEVOLUCION_DIAS, PLAZO_GARANTIA_DIAS, Cliente, DetalleDevolucion,
    DetalleFactura, Devolucion, Factura, Garantia, Producto, SeguimientoGarantia,
)

# Create your views here.

CODIGO_PRODUCTO = re.compile(r'^[0-9]{3}[A-Z]{3}$')
STOCK_BAJO = 5      # desde aquí se avisa que quedan pocas unidades

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
    # Unidades compradas y devueltas (subconsultas para no duplicar sumas por los joins)
    comprado = (DetalleFactura.objects.filter(factura=OuterRef('pk'))
                .values('factura').annotate(s=Sum('cantidad')).values('s'))
    devuelto = (DetalleDevolucion.objects.filter(detalle_factura__factura=OuterRef('pk'))
                .values('detalle_factura__factura').annotate(s=Sum('cantidad')).values('s'))
    facturas = Factura.objects.select_related('cliente').annotate(
        unidades=Coalesce(Subquery(comprado), 0),
        devueltas=Coalesce(Subquery(devuelto), 0),
    )

    numero = request.GET.get('numero', '').strip()
    cliente = request.GET.get('cliente', '').strip()
    fecha = request.GET.get('fecha', '').strip()

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
                | Q(cliente__documento__icontains=palabra)
            )

    if fecha and _fecha(fecha):
        facturas = facturas.filter(fecha_factura=_fecha(fecha))

    return render(request, 'consulta_factura.html', {
        'facturas': [{
            'numero': f.numero,
            'cliente': f.cliente.nombre_completo,
            'fecha': f.fecha_factura.strftime('%d/%m/%Y'),
            'total': _cop(f.total),
            'estado': _estado_factura(f),
        } for f in facturas[:200]],
        'f': {'numero': numero, 'cliente': cliente, 'fecha': fecha},
    })

def _estado_factura(f):
    """(texto, clase de la píldora) según si está anulada o tiene devoluciones."""
    if f.estado == Factura.Estado.ANULADA:
        return 'Anulada', 'pill-error'
    if f.devueltas and f.devueltas >= f.unidades:
        return 'Devuelta', 'pill-off'
    if f.devueltas:
        return 'Devolución parcial', 'pill-warn'
    return 'Activa', 'pill-ok'

@login_required
@permission_required('facturacion.add_factura', raise_exception=True)
def nueva_factura(request):
    url = reverse('nueva_factura')
    hoy = timezone.localdate()
    productos = Producto.objects.filter(activo=True)

    if request.method == 'POST':
        cliente = Cliente.objects.filter(pk=request.POST.get('cliente', '').strip()).first()
        fecha = _fecha(request.POST.get('fecha'))
        errores = []

        if cliente is None:
            errores.append('Selecciona el cliente (si no existe, créalo primero).')
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

        if errores:
            for e in errores:
                messages.error(request, e)
            return redirect(url)

        with transaction.atomic():
            # Se bloquean las filas para que dos ventas a la vez no descuenten el mismo stock.
            # El precio se toma SIEMPRE de la base de datos, nunca del navegador.
            encontrados = {p.pk: p for p in productos.select_for_update().filter(pk__in=pedido)}
            if len(encontrados) != len(pedido):
                errores.append('Alguno de los productos ya no está disponible.')
            for pid, cant in pedido.items():
                p = encontrados.get(pid)
                if p and cant > p.stock:
                    errores.append(
                        f'No hay suficiente stock de «{p.nombre_producto}»: '
                        f'quedan {p.stock} y pediste {cant}.')

            if not errores:
                factura = Factura.objects.create(
                    fecha_factura=fecha, cliente=cliente, usuario=request.user)

                total = 0
                for pid, cant in pedido.items():
                    p = encontrados[pid]
                    acumulado = p.precio_venta_unitario * cant
                    DetalleFactura.objects.create(
                        factura=factura, producto=p, cantidad=cant, precio_acumulado=acumulado)
                    Producto.objects.filter(pk=pid).update(stock=F('stock') - cant)
                    total += acumulado

                factura.total = total
                factura.save(update_fields=['total'])

        if errores:
            for e in errores:
                messages.error(request, e)
            return redirect(url)

        registrar(request, Auditoria.Evento.CREACION,
                  f'Factura {factura.numero} de {cliente.nombre_completo} por {_cop(total)}')
        messages.success(request, f'Factura {factura.numero} generada por {_cop(total)}.')
        return redirect(url)

    return render(request, 'fac_nueva.html', {
        # Se renombran las claves para que el HTML y el JS sigan funcionando igual
        'productos': list(
            productos.annotate(nombre=F('nombre_producto'), precio=F('precio_venta_unitario'))
            .values('id', 'codigo', 'nombre', 'precio', 'stock')
        ),
        'clientes': Cliente.objects.all(),
        'cliente_nuevo': request.GET.get('cliente', ''),
        'hoy': hoy.isoformat(),
    })


def _url_pdf(request):
    """La misma URL del reporte (con sus filtros) pidiendo el PDF."""
    q = request.GET.copy()
    q['formato'] = 'pdf'
    return '?' + q.urlencode()


def _texto(request, campo, largo):
    """Valor del formulario sin espacios repetidos."""
    return ' '.join(request.POST.get(campo, '').split())[:largo]


@login_required
@permission_required('facturacion.add_cliente', raise_exception=True)
def crear_cliente(request):
    url = reverse('crear_cliente')
    valores = {}

    if request.method == 'POST':
        valores = {
            'nombres': _texto(request, 'nombres', 100),
            'apellidos': _texto(request, 'apellidos', 100),
            # Se aceptan puntos, guiones y espacios al escribir (1.012.345), pero se guardan solo los dígitos
            'documento': re.sub(r'[\s.\-]', '', request.POST.get('documento', ''))[:15],
            'telefono': re.sub(r'[\s.\-]', '', request.POST.get('telefono', ''))[:15],
            'correo': _texto(request, 'correo', 100).lower(),
        }
        errores = []
        if not re.fullmatch(r'[0-9]{5,15}', valores['documento']):
            errores.append('El documento debe tener solo números (entre 5 y 15 dígitos).')
        elif Cliente.objects.filter(documento=valores['documento']).exists():
            errores.append(f'Ya existe un cliente con el documento {valores["documento"]}.')
        if not valores['nombres'] or not valores['apellidos']:
            errores.append('Escribe los nombres y apellidos del cliente.')
        if not re.fullmatch(r'[0-9]{7,15}', valores['telefono']):
            errores.append('El teléfono debe tener solo números (entre 7 y 15 dígitos).')
        if not valores['correo'] or '@' not in valores['correo']:
            errores.append('Escribe un correo válido.')

        if not errores:
            cliente = Cliente.objects.create(
                nombres=valores['nombres'], apellidos=valores['apellidos'],
                documento=valores['documento'],
                telefono=valores['telefono'], correo=valores['correo'])
            registrar(request, Auditoria.Evento.CREACION, f'Cliente {cliente.nombre_completo}')
            messages.success(request, f'Cliente {cliente.nombre_completo} creado.')
            # Si se vino desde la factura, se vuelve a ella con el cliente ya elegido
            if request.POST.get('volver') == 'factura' and request.user.has_perm('facturacion.add_factura'):
                return redirect(f'{reverse("nueva_factura")}?{urlencode({"cliente": cliente.pk})}')
            return redirect(url)

        for e in errores:
            messages.error(request, e)

    return render(request, 'clientes.html', {
        'valores': valores,
        'volver': request.POST.get('volver') or request.GET.get('volver', ''),
        'clientes': Cliente.objects.all()[:200],
    })


@login_required
@permission_required('facturacion.add_producto', raise_exception=True)
def crear_producto(request):
    url = reverse('crear_producto')
    valores = {}

    if request.method == 'POST':
        accion = request.POST.get('accion', 'crear')

        # ---------- Sumar unidades a un producto existente ----------
        if accion == 'stock':
            producto = Producto.objects.filter(pk=_entero(request.POST.get('producto'))).first()
            cant = _entero(request.POST.get('unidades'), 1, 100000)
            if producto is None or cant is None:
                messages.error(request, 'Escribe una cantidad válida de unidades a agregar.')
                return redirect(url)
            Producto.objects.filter(pk=producto.pk).update(stock=F('stock') + cant)
            producto.refresh_from_db(fields=['stock'])
            registrar(request, Auditoria.Evento.CREACION,
                      f'Ingreso de {cant} unidades de {producto.codigo} (stock {producto.stock})')
            messages.success(
                request, f'Se agregaron {cant} unidades a {producto.codigo}. Stock actual: {producto.stock}.')
            return redirect(url)

        # ---------- Crear producto ----------
        valores = {
            'codigo': _texto(request, 'codigo', 10).upper().replace(' ', ''),
            'nombre': _texto(request, 'nombre', 100),
            'precio': request.POST.get('precio', '').strip(),
            'stock': request.POST.get('stock', '').strip(),
        }
        precio = _entero(valores['precio'], 1)
        stock = _entero(valores['stock'], 0, 100000)
        errores = []
        if not CODIGO_PRODUCTO.match(valores['codigo']):
            errores.append('El código debe tener 3 números y 3 letras (ej. 301BLU).')
        elif Producto.objects.filter(codigo=valores['codigo']).exists():
            errores.append(f'Ya existe un producto con el código {valores["codigo"]}.')
        if not valores['nombre']:
            errores.append('Escribe el nombre del producto.')
        if precio is None:
            errores.append('El precio debe ser un número entero mayor que 0.')
        if stock is None:
            errores.append('La cantidad inicial debe ser un número entero (0 o más).')

        if not errores:
            producto = Producto.objects.create(
                codigo=valores['codigo'], nombre_producto=valores['nombre'],
                precio_venta_unitario=precio, stock=stock)
            registrar(request, Auditoria.Evento.CREACION,
                      f'Producto {producto} con {stock} unidades')
            messages.success(request, f'Producto {producto} creado con {stock} unidades.')
            return redirect(url)

        for e in errores:
            messages.error(request, e)

    buscar = request.GET.get('buscar', '').strip()
    productos = Producto.objects.all()
    if buscar:
        productos = productos.filter(
            Q(codigo__icontains=buscar) | Q(nombre_producto__icontains=buscar))

    return render(request, 'productos.html', {
        'valores': valores,
        'buscar': buscar,
        'productos': [{
            'p': p,
            'precio': _cop(p.precio_venta_unitario),
            'clase': 'pill-error' if p.stock == 0 else 'pill-warn' if p.stock <= STOCK_BAJO else 'pill-ok',
        } for p in productos[:300]],
        'stock_bajo': STOCK_BAJO,
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
    barras, serie = [], []
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

    if request.GET.get('formato') == 'pdf':
        nombre_vendedor = next((v['nombre'] for v in vendedores if str(v['id']) == vendedor), 'Todos')
        p = Producto.objects.filter(pk=_entero(producto)).first() if _entero(producto) else None
        contenido = [
            pdf.tabla(['Total vendido', 'N.º de ventas', 'Venta promedio'],
                      [[_cop(total), ventas, _cop(total // ventas if ventas else 0)]],
                      derecha=(0, 1, 2), anchos=[17 / 3 * pdf.cm] * 3),
            pdf.parrafo('Ventas por vendedor', 'Heading2'),
            pdf.tabla(
                ['Vendedor', 'N.º ventas', 'Total'],
                [[f['nombre'], f['ventas'], f['total']] for f in por_vendedor]
                or [['No hay ventas con estos filtros.', '', '']],
                derecha=(1, 2),
                total=['Total', ventas, _cop(total)] if len(por_vendedor) > 1 else None,
                anchos=[9 * pdf.cm, 3.5 * pdf.cm, 4.5 * pdf.cm],
            ),
        ]
        if serie:
            contenido += [
                pdf.parrafo('Ventas por periodo', 'Heading2'),
                pdf.grafico_barras([e for e, _ in serie], [t for _, t in serie]),
            ]
        filtros = [('Periodo', dict(PERIODOS)[periodo]), ('Vendedor', nombre_vendedor),
                   ('Producto', str(p) if p else 'Todos')]
        registrar(request, Auditoria.Evento.DESCARGA,
                  'Reporte de ventas en PDF (' + ', '.join(f'{k}: {v}' for k, v in filtros) + ')')
        return pdf.reporte(
            'Reporte de ventas', filtros,
            contenido, request.user,
            f'reporte_ventas_{timezone.localdate():%Y-%m-%d}.pdf',
        )

    return render(request, 'reporte_ventas.html', {
        'url_pdf': _url_pdf(request),
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


def _lineas_garantia(factura):
    """Productos de la factura con las unidades que aún pueden entrar en garantía:
    lo comprado menos lo devuelto y lo que ya está en una garantía abierta."""
    devuelto = (DetalleDevolucion.objects.filter(detalle_factura=OuterRef('pk'))
                .values('detalle_factura').annotate(s=Sum('cantidad')).values('s'))
    en_garantia = (Garantia.objects.filter(detalle_factura=OuterRef('pk'),
                                           estado__in=ESTADOS_ABIERTOS)
                   .values('detalle_factura').annotate(s=Sum('cantidad')).values('s'))
    detalles = factura.detalles.select_related('producto').annotate(
        devuelto=Coalesce(Subquery(devuelto), 0),
        en_garantia=Coalesce(Subquery(en_garantia), 0),
    ).order_by('pk')
    return [{
        'detalle': d,
        'comprado': d.cantidad,
        'disponible': max(0, d.cantidad - d.devuelto - d.en_garantia),
    } for d in detalles]


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
def solicitud_garantia(request):
    # Vendedor crea, auxiliar hace el seguimiento y gerente aprueba o rechaza (RF-FACT-07):
    # basta con tener cualquiera de los tres permisos para entrar.

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

            pk = _entero(request.POST.get('detalle'))
            linea = next((l for l in _lineas_garantia(factura) if l['detalle'].pk == pk), None)
            descripcion = request.POST.get('descripcion', '').strip()[:1000]

            errores = _problemas_garantia(factura)
            cant = None
            if linea is None:
                errores.append('Selecciona un producto de la factura.')
            elif not linea['disponible']:
                errores.append('Ese producto no tiene unidades disponibles para garantía '
                               '(ya fueron devueltas o están en una garantía en curso).')
            else:
                cant = _entero(request.POST.get('cantidad'), 1, linea['disponible'])
                if cant is None:
                    errores.append(f'Cantidad no válida (máximo {linea["disponible"]}).')
            if not descripcion:
                errores.append('Describe la falla del producto.')

            if errores:
                for e in errores:
                    messages.error(request, e)
                return redirect(back)

            detalle = linea['detalle']
            garantia = Garantia.objects.create(
                detalle_factura=detalle, cantidad=cant,
                descripcion=descripcion, usuario_vendedor=u)
            registrar(request, Auditoria.Evento.CREACION,
                      f'Garantía {garantia.numero}: {cant} × {detalle.producto.nombre_producto} '
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
                registrar(request, Auditoria.Evento.MODIFICACION,
                          f'Garantía {garantia.numero} pasó a "{garantia.get_estado_display()}"')
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
                registrar(request, Auditoria.Evento.MODIFICACION,
                          f'Garantía {garantia.numero} {garantia.get_estado_display().lower()}')

            messages.success(request, f'{garantia.numero}: {garantia.get_estado_display().lower()}.')
            return redirect(url)

        return redirect(url)

    # ---------- Mostrar ----------
    texto = request.GET.get('factura', '').strip()
    factura, lineas, problemas = None, [], []
    if texto and puede_crear:
        factura = _buscar_factura(texto)
        if factura is None:
            messages.error(request, f'No existe la factura "{texto}".')
        else:
            lineas = _lineas_garantia(factura)
            problemas = _problemas_garantia(factura)
            if not any(l['disponible'] for l in lineas):
                problemas.append('Ningún producto de esta factura tiene unidades disponibles '
                                 'para garantía.')

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
        'texto': texto, 'factura': factura, 'lineas': lineas, 'problemas': problemas,
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
        return grupos.setdefault(
            k, {'dev': 0, 'uds': 0, 'gar': 0, 'uds_gar': 0, 'motivos': Counter()})

    for l in devs:
        g = grupo(clave(l.detalle_factura, l.devolucion.fecha_devolucion))
        g['dev'] += 1
        g['uds'] += l.cantidad
        g['motivos'][l.devolucion.get_motivo_display()] += 1
    for gr in gars:
        g = grupo(clave(gr.detalle_factura, gr.fecha_solicitud))
        g['gar'] += 1
        g['uds_gar'] += gr.cantidad

    filas = []
    for nombre, g in grupos.items():
        top = sorted(g['motivos'].items(), key=lambda kv: (-kv[1], kv[0]))
        filas.append({
            'grupo': nombre,
            'devoluciones': g['dev'],
            'unidades': g['uds'],
            'garantias': g['gar'],
            'unidades_gar': g['uds_gar'],
            'motivo': top[0][0] if top else '—',
        })

    if agrupar == 'mes':
        filas.sort(key=lambda f: f['grupo'], reverse=True)
    else:
        filas.sort(key=lambda f: (-(f['devoluciones'] + f['garantias']), f['grupo']))

    titulo_grupo = {'producto': 'Producto', 'cliente': 'Clienta', 'mes': 'Mes'}[agrupar]
    total_dev = sum(f['devoluciones'] for f in filas)
    total_uds = sum(f['unidades'] for f in filas)
    total_gar = sum(f['garantias'] for f in filas)
    total_uds_gar = sum(f['unidades_gar'] for f in filas)

    if request.GET.get('formato') == 'pdf':
        p = Producto.objects.filter(pk=_entero(producto)).first() if _entero(producto) else None
        contenido = [
            pdf.tabla(
                [titulo_grupo, 'N.º devoluciones', 'Unidades devueltas', 'N.º garantías',
                 'Unidades en garantía', 'Motivo más frecuente'],
                [[f['grupo'], f['devoluciones'], f['unidades'], f['garantias'],
                  f['unidades_gar'], f['motivo']] for f in filas]
                or [['No hay devoluciones ni garantías con estos filtros.', '', '', '', '', '']],
                derecha=(1, 2, 3, 4),
                total=(['Total', total_dev, total_uds, total_gar, total_uds_gar, '']
                       if len(filas) > 1 else None),
                anchos=[3.8 * pdf.cm, 2.6 * pdf.cm, 2.8 * pdf.cm, 2.2 * pdf.cm, 2.6 * pdf.cm,
                        3.0 * pdf.cm],
            ),
            pdf.Spacer(1, 0.4 * pdf.cm),
            pdf.parrafo(
                '<font color="#6b6b72">Cada producto devuelto cuenta como una devolución. '
                'El motivo es solo de las devoluciones; al filtrar por motivo, '
                'las garantías no se cuentan.</font>'),
        ]
        filtros = [('Periodo', dict(PERIODOS)[periodo]), ('Producto', str(p) if p else 'Todos'),
                   ('Motivo', dict(Devolucion.Motivo.choices).get(motivo, 'Todos')),
                   ('Agrupado por', titulo_grupo)]
        registrar(request, Auditoria.Evento.DESCARGA,
                  'Reporte de devoluciones y garantías en PDF ('
                  + ', '.join(f'{k}: {v}' for k, v in filtros) + ')')
        return pdf.reporte(
            'Reporte de devoluciones y garantías', filtros,
            contenido, request.user,
            f'reporte_devoluciones_garantias_{timezone.localdate():%Y-%m-%d}.pdf',
        )

    return render(request, 'reporte_dg.html', {
        'url_pdf': _url_pdf(request),
        'periodos': PERIODOS, 'periodo': periodo,
        'producto': producto, 'motivo': motivo, 'agrupar': agrupar,
        'productos': Producto.objects.all(),
        'motivos': Devolucion.Motivo.choices,
        'filas': filas,
        'total_dev': total_dev,
        'total_uds': total_uds,
        'total_gar': total_gar,
        'total_uds_gar': total_uds_gar,
        'titulo_grupo': titulo_grupo,
    })