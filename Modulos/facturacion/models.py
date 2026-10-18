from django.conf import settings
from django.db import models

PLAZO_DEVOLUCION_DIAS = 30   # días desde la fecha de la factura


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


class Devolucion(models.Model):                       # DEVOLUCION
    class Motivo(models.TextChoices):
        TALLA = 'talla_incorrecta', 'Talla incorrecta'
        DEFECTUOSO = 'defectuoso', 'Producto defectuoso'
        OTRO = 'otro', 'Otro'

    class Resolucion(models.TextChoices):
        REEMBOLSO = 'reembolso', 'Reembolso'
        CAMBIO = 'cambio', 'Cambio de producto'
        NOTA_CREDITO = 'nota_credito', 'Nota crédito'

    factura = models.ForeignKey(Factura, on_delete=models.PROTECT, related_name='devoluciones')
    motivo = models.CharField(max_length=20, choices=Motivo.choices)
    fecha_devolucion = models.DateTimeField(auto_now_add=True)
    tipo_resolucion = models.CharField(max_length=20, choices=Resolucion.choices)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='devoluciones'
    )

    class Meta:
        ordering = ['-fecha_devolucion']

    def __str__(self):
        return f'Devolución {self.numero}'

    @property
    def numero(self):
        return f'D-{self.pk:04d}'


class DetalleDevolucion(models.Model):                # DETALLE_DEVOLUCION
    devolucion = models.ForeignKey(Devolucion, on_delete=models.CASCADE, related_name='lineas')
    detalle_factura = models.ForeignKey(
        DetalleFactura, on_delete=models.PROTECT, related_name='lineas_devueltas'
    )
    cantidad = models.PositiveIntegerField()