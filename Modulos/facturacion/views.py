from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from Modulos.facturacion.catalogo import PRODUCTOS


# Create your views here.

@login_required
def consulta_facturas(request):
    facturas = [
        {'numero': '0001245', 'cliente': 'María Gómez', 'fecha': '20/09/2026', 'total': '$209.000', 'estado': 'Pagada', 'clase': 'pill-ok'},
        {'numero': '0001246', 'cliente': 'Diana Pérez', 'fecha': '21/09/2026', 'total': '$145.000', 'estado': 'Pendiente', 'clase': 'pill-warn'},
        {'numero': '0001247', 'cliente': 'Laura Ríos', 'fecha': '15/09/2026', 'total': '$98.000', 'estado': 'Vencida', 'clase': 'pill-error'},
        {'numero': '0001248', 'cliente': 'Sara Molina', 'fecha': '10/09/2026', 'total': '$60.000', 'estado': 'Anulada', 'clase': 'pill-off'},
    ]
    estados = ['Pagada', 'Pendiente', 'Vencida', 'Anulada']
    return render(request, 'consulta_factura.html', {
        'facturas': facturas,
        'estados': estados,
    })
@login_required
def nueva_factura(request):
    clientes = ['María Gómez', 'Diana Pérez', 'Laura Ríos', 'Sara Molina']
    return render(request, 'fac_nueva.html', {
        'clientes': clientes,
        'productos': PRODUCTOS,
        'hoy': timezone.localdate().isoformat(),
    })