from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from Modulos.usuarios.models import Empleado, Usuario


class UsuarioCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = Usuario
        fields = ("username", "email", "empleado")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["empleado"].required = True


class UsuarioChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["empleado"].required = True


admin.site.register(Empleado)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = UsuarioCreationForm
    form = UsuarioChangeForm

    fieldsets = UserAdmin.fieldsets + (
        ("Información adicional", {"fields": ("empleado",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Información adicional", {"fields": ("email", "empleado")}),
    )