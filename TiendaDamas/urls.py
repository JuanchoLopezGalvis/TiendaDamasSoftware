"""
URL configuration for TiendaDamas project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin

from django.urls import path
from django.contrib.auth import views as auth_views
from Modulos.usuarios import views as usuario_views
from Modulos.facturacion import views as facturacion_views
urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', usuario_views.panel, name='panel'),
    path('panel/empleados/', usuario_views.crear_empleado, name='crear_empleado'),
    path('panel/registro-usuario/', usuario_views.registro_usuario, name='registro_usuario'),
    path('panel/roles-permisos/', usuario_views.roles_permisos, name='roles_permisos'),
    path('panel/asignacion-roles/', usuario_views.asignacion_roles, name='asignacion_roles'),
    path('panel/bitacora-auditoria/', usuario_views.bitacora_auditoria, name='bitacora_auditoria'),
    path('panel/cambiar-clave/', usuario_views.CambiarClaveView.as_view(), name='cambiar_clave'),
    path('panel/perfil/', usuario_views.perfil, name='perfil'),
    path('panel/consulta/', usuario_views.consulta, name='consulta'),
    path('recuperar-clave/', usuario_views.recuperar_clave, name='recuperar_clave'),
    path('panel/facturacion/consulta/', facturacion_views.consulta_facturas, name='consulta_facturas'),
    path('panel/facturacion/clientes/', facturacion_views.crear_cliente, name='crear_cliente'),
    path('panel/facturacion/productos/', facturacion_views.crear_producto, name='crear_producto'),
    path('panel/facturacion/nueva/', facturacion_views.nueva_factura, name='nueva_factura'),
    path('panel/facturacion/reporte-ventas/', facturacion_views.reporte_ventas, name='reporte_ventas'),
    path('panel/facturacion/devolucion/', facturacion_views.registrar_devolucion, name='registrar_devolucion'),
    path('panel/facturacion/garantia/', facturacion_views.solicitud_garantia, name='solicitud_garantia'),
    path('panel/facturacion/reporte-devoluciones-garantias/', facturacion_views.reporte_dg, name='reporte_dg'),
]
