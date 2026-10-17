from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from Modulos.facturacion.models import Cliente, DetalleFactura, Factura, Producto
from Modulos.usuarios.auditoria import registrar
from Modulos.usuarios.models import Auditoria

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
@login_required
def reporte_ventas(request):
    return render(request, 'reporte_ventas.html')


@login_required
def registrar_devolucion(request):
    return render(request, 'devolucion.html')


@login_required
def solicitud_garantia(request):
    return render(request, 'garantia.html')


@login_required
def reporte_dg(request):
    return render(request, 'reporte_dg.html')