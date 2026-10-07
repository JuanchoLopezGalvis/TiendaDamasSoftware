from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.

class Empleado(models.Model):
    documento_identidad = models.CharField(max_length=50, primary_key=True)
    nombre_completo = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre_completo

class Usuario(AbstractUser):
    empleado = models.ForeignKey(
        Empleado,
        on_delete=models.PROTECT,
        db_column='documento_identidad'
    )

