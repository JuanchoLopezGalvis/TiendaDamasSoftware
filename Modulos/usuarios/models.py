from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

from TiendaDamas import settings


# Create your models here.

class Empleado(models.Model):
    # Cédula: solo números (se guarda como texto para no perder ceros a la izquierda)
    documento_identidad = models.CharField(
        max_length=50, primary_key=True,
        validators=[RegexValidator(r'^[0-9]+$', 'Solo se permiten números.')],
    )
    nombre_completo = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre_completo

class Usuario(AbstractUser):
    empleado = models.ForeignKey(
        Empleado,
        on_delete=models.PROTECT,
        db_column='documento_identidad',
        null=True,
    )

class Auditoria(models.Model):
    class Evento(models.TextChoices):
        INICIO_SESION = 'inicio_sesion', 'Inicio de sesión'
        ACCESO_DENEGADO = 'acceso_denegado', 'Acceso denegado'
        CAMBIO_ROL = 'cambio_rol', 'Cambio de rol'
        CREACION = 'creacion', 'Creación'
        MODIFICACION = 'modificacion', 'Modificación'
        DESCARGA = 'descarga', 'Descarga de reporte'
        CIERRE_SESION = 'cierre_sesion', 'Cierre de sesión'

    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    usuario_texto = models.CharField(max_length=150, blank=True)
    evento = models.CharField(max_length=20, choices=Evento.choices)
    detalle = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha']
        default_permissions = ('view',)

    def __str__(self):
        return f'{self.fecha:%d/%m/%Y %H:%M} - {self.evento}'