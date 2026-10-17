from django.conf import settings
from django.db import models


class Cliente(models.Model):                          # CLIENTES
    nombres = models.CharField(max_length=100)        # nombres_cliente
    apellidos = models.CharField(max_length=100)      # apellidos_cliente

    class Meta:
        ordering = ['nombres', 'apellidos']

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellidos}'.strip()

    def __str__(self):
        return self.nombre_completo


class Producto(models.Model):                         # PRODUCTOS
    codigo = models.CharField(max_length=10, unique=True)      # extra: no está en el diagrama
    nombre_producto = models.CharField(max_length=100)
    precio_venta_unitario = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)                  # extra

    class Meta:
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} - {self.nombre_producto}'


class Factura(models.Model):                          # FACTURA
    class Estado(models.TextChoices):
        PAGADA = 'pagada', 'Pagada'
        PENDIENTE = 'pendiente', 'Pendiente'
        VENCIDA = 'vencida', 'Vencida'
        ANULADA = 'anulada', 'Anulada'

    fecha_factura = models.DateField()
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='facturas')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='facturas'
    )
    total = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PAGADA)

    class Meta:
        ordering = ['-fecha_factura', '-pk']

    def __str__(self):
        return f'Factura {self.numero}'

    @property
    def numero(self):
        return f'{self.pk:07d}'        # 0000001

    @property
    def clase(self):
        return {
            'pagada': 'pill-ok',
            'pendiente': 'pill-warn',
            'vencida': 'pill-error',
            'anulada': 'pill-off',
        }.get(self.estado, 'pill-off')


class DetalleFactura(models.Model):                   # DETALLE_FACTURA
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='ventas')
    cantidad = models.PositiveIntegerField()
    precio_acumulado = models.PositiveIntegerField()   # cantidad × precio unitario