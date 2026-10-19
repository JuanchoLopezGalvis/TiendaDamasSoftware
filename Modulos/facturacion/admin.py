from django.contrib import admin

from Modulos.facturacion.models import (
    Cliente, DetalleDevolucion, DetalleFactura, Devolucion, Factura,
    Garantia, Producto, SeguimientoGarantia,
)



class DetalleInline(admin.TabularInline):
    model = DetalleFactura
    extra = 0
    can_delete = False
    readonly_fields = ('producto', 'cantidad', 'precio_acumulado')


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'cliente', 'usuario', 'fecha_factura', 'total', 'estado')
    list_filter = ('estado', 'fecha_factura')
    inlines = [DetalleInline]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre_producto', 'precio_venta_unitario', 'activo')
    search_fields = ('codigo', 'nombre_producto')


admin.site.register(Cliente)



class LineaDevolucionInline(admin.TabularInline):
    model = DetalleDevolucion
    extra = 0
    can_delete = False
    readonly_fields = ('detalle_factura', 'cantidad')


@admin.register(Devolucion)
class DevolucionAdmin(admin.ModelAdmin):
    list_display = ('numero', 'factura', 'motivo', 'tipo_resolucion', 'usuario', 'fecha_devolucion')
    list_filter = ('motivo', 'tipo_resolucion')
    inlines = [LineaDevolucionInline]



class SeguimientoInline(admin.TabularInline):
    model = SeguimientoGarantia
    extra = 0
    can_delete = False
    readonly_fields = ('usuario_auxiliar', 'estado', 'fecha')


@admin.register(Garantia)
class GarantiaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'detalle_factura', 'estado', 'usuario_vendedor',
                    'usuario_gerente', 'fecha_solicitud')
    list_filter = ('estado',)
    inlines = [SeguimientoInline]