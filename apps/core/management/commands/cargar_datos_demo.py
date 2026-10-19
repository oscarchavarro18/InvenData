"""Carga datos de demostración para probar la aplicación en pantalla.

Crea ubicaciones, tipos de embalaje, productos, un proveedor, dos usuarios y un documento
del proveedor abierto con dos líneas. Se puede repetir sin duplicar nada: lo que ya existe
se deja tal cual (incluidos los usuarios y sus contraseñas).

    python manage.py cargar_datos_demo --clave <contraseña>
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Perfil, Usuario
from apps.maestros.models import (
    CategoriaProducto,
    Producto,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea

UBICACIONES = [
    ("TUN-01", "Túnel de congelación 1", "TUNEL_CONGELACION"),
    ("SOST-01", "Cuarto de sostenimiento", "SOSTENIMIENTO"),
    ("BUL-01", "Zona de bultos", "ZONA_BULTOS"),
    ("TRF-01", "Zona de transformación", "ZONA_TRANSFORMACION"),
    ("PDV-01", "Punto de venta 1", "PUNTO_VENTA"),
]
EMBALAJES = [
    ("Canastilla", Decimal("2.50")),
    ("Caja de icopor", Decimal("1.20")),
    ("Sin embalaje", Decimal("0")),
]
PRODUCTOS = [
    ("POL-001", "Pechuga de pollo", "Pollo", False),
    ("PES-001", "Tilapia entera", "Pescado y mariscos", True),
    ("CAM-001", "Camarón", "Pescado y mariscos", True),
]


class Command(BaseCommand):
    help = "Crea datos de demostración (se puede repetir sin duplicar)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clave", required=True, help="Contraseña de los usuarios de demostración."
        )

    @transaction.atomic
    def handle(self, *args, clave, **opciones):
        for codigo, nombre, tipo in UBICACIONES:
            Ubicacion.objects.get_or_create(
                codigo=codigo, defaults={"nombre": nombre, "tipo": tipo}
            )
        for nombre, tara in EMBALAJES:
            TipoEmbalaje.objects.get_or_create(nombre=nombre, defaults={"peso_tara": tara})
        for codigo, nombre, categoria, transforma in PRODUCTOS:
            categoria_obj, _ = CategoriaProducto.objects.get_or_create(nombre=categoria)
            Producto.objects.get_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "unidad_medida": "KG",
                    "categoria": categoria_obj,
                    "admite_transformacion": transforma,
                },
            )

        proveedor, _ = Proveedor.objects.get_or_create(
            tipo_documento="NIT",
            numero_documento="900123456",
            defaults={"razon_social": "Avícola del Huila"},
        )

        creados = []
        if not Usuario.objects.filter(usuario="gerente").exists():
            Usuario.objects.create_superuser(
                "gerente", clave, nombre_completo="Gerente de demostración"
            )
            creados.append("gerente")
        if not Usuario.objects.filter(usuario="jefe").exists():
            Usuario.objects.create_user(
                "jefe",
                clave,
                nombre_completo="Jefe de bodega de demostración",
                perfil=Perfil.objects.get(codigo=Perfil.Codigo.JEFE_BODEGA),
            )
            creados.append("jefe")

        documento, nuevo = DocumentoProveedor.objects.get_or_create(
            proveedor=proveedor,
            tipo_documento="REMISION",
            numero_documento="REM-0001",
            defaults={"fecha": timezone.localdate()},
        )
        if nuevo:
            for codigo, cantidad in (("POL-001", "100"), ("PES-001", "60")):
                DocumentoProveedorLinea.objects.create(
                    documento_proveedor=documento,
                    producto=Producto.objects.get(codigo=codigo),
                    cantidad=Decimal(cantidad),
                )

        usuarios = ", ".join(creados) if creados else "ninguno (ya existían)"
        self.stdout.write(
            self.style.SUCCESS(f"Datos de demostración listos. Usuarios nuevos: {usuarios}.")
        )
