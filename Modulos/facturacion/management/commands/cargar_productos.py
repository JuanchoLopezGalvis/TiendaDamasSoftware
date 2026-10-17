from django.core.management.base import BaseCommand

from Modulos.facturacion.catalogo import PRODUCTOS
from Modulos.facturacion.models import Producto


class Command(BaseCommand):
    help = 'Carga (o actualiza) en la base de datos los productos de catalogo.py'

    def handle(self, *args, **options):
        creados = actualizados = 0
        for p in PRODUCTOS:
            _, nuevo = Producto.objects.update_or_create(
                codigo=p['codigo'],
                defaults={
                    'nombre_producto': p['nombre'],
                    'precio_venta_unitario': p['precio'],
                },
            )
            if nuevo:
                creados += 1
            else:
                actualizados += 1
        self.stdout.write(self.style.SUCCESS(
            f'Productos: {creados} creados, {actualizados} actualizados.'
        ))