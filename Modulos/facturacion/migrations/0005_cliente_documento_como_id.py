"""El documento pasa a ser la llave primaria de Cliente (antes era un id numérico).

Las facturas existentes se reasignan al documento de su cliente. A los clientes
que no tenían documento (o lo tenían con letras) se les pone uno provisional con ceros a la izquierda
(ej. 000000000000001) para no perderlos; luego se debe corregir por la cédula real.
"""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def documentos_provisionales(apps, schema_editor):
    Cliente = apps.get_model('facturacion', 'Cliente')
    for c in Cliente.objects.all():
        if not (c.documento or '').isdigit():
            c.documento = f'{c.pk:015d}'
            c.save(update_fields=['documento'])


def copiar_documento_a_factura(apps, schema_editor):
    Factura = apps.get_model('facturacion', 'Factura')
    for f in Factura.objects.select_related('cliente'):
        f.cliente_doc = f.cliente.documento
        f.save(update_fields=['cliente_doc'])


def enlazar_factura_por_documento(apps, schema_editor):
    Factura = apps.get_model('facturacion', 'Factura')
    for f in Factura.objects.all():
        f.cliente_id = f.cliente_doc
        f.save(update_fields=['cliente'])


class Migration(migrations.Migration):

    dependencies = [
        ('facturacion', '0004_cliente_datos_producto_stock'),
    ]

    operations = [
        migrations.RunPython(documentos_provisionales, migrations.RunPython.noop),

        # Se guarda el documento del cliente en cada factura y se suelta la FK vieja
        migrations.AddField(
            model_name='factura', name='cliente_doc',
            field=models.CharField(max_length=15, null=True),
        ),
        migrations.RunPython(copiar_documento_a_factura, migrations.RunPython.noop),
        migrations.RemoveField(model_name='factura', name='cliente'),

        # Cliente: documento como llave primaria; teléfono y correo obligatorios
        migrations.RemoveField(model_name='cliente', name='id'),
        migrations.AlterField(
            model_name='cliente', name='documento',
            field=models.CharField(
                max_length=15, primary_key=True, serialize=False,
                validators=[django.core.validators.RegexValidator('^[0-9]+$', 'Solo se permiten números.')]),
        ),
        migrations.AlterField(
            model_name='cliente', name='telefono',
            field=models.CharField(
                max_length=15,
                validators=[django.core.validators.RegexValidator('^[0-9]+$', 'Solo se permiten números.')]),
        ),
        migrations.AlterField(
            model_name='cliente', name='correo',
            field=models.EmailField(max_length=100),
        ),

        # Se vuelve a crear la FK, ahora apuntando al documento
        migrations.AddField(
            model_name='factura', name='cliente',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='facturas', to='facturacion.cliente'),
        ),
        migrations.RunPython(enlazar_factura_por_documento, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='factura', name='cliente',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='facturas', to='facturacion.cliente'),
        ),
        migrations.RemoveField(model_name='factura', name='cliente_doc'),
    ]
