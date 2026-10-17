from django.contrib import admin

from Modulos.facturacion.models import Cliente, DetalleFactura, Factura, Producto


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