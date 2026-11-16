"""Los maestros que administra el Gerente y cómo se muestra cada uno (RF-02, RF-04 a RF-08).

Cada catálogo dice su modelo, su formulario, por qué campos se busca, qué columnas lleva la
lista y si se activa o desactiva. Las pantallas de Administración son genéricas y leen de
aquí, así todos los maestros se ven y se comportan igual.
"""

from dataclasses import dataclass, field

from apps.maestros.forms import (
    CategoriaForm,
    ClienteForm,
    EmbalajeForm,
    ParametroValorForm,
    ProveedorForm,
    UbicacionForm,
)
from apps.maestros.models import (
    CategoriaProducto,
    Cliente,
    Parametro,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)


@dataclass(frozen=True)
class Columna:
    titulo: str
    valor: object  # función que recibe el objeto y devuelve el texto
    estilo: str = ""  # "", "codigo" (letra de máquina) o "num"


@dataclass(frozen=True)
class Catalogo:
    clave: str  # prefijo de los nombres de ruta: «ubicacion» → maestros:ubicacion_lista
    ruta_base: str  # segmento de la dirección: /administracion/<ruta_base>/
    articulo: str  # «el» o «la», para los mensajes
    singular: str
    plural: str
    descripcion: str
    icono: str
    modelo: type
    formulario: type
    busqueda: tuple
    columnas: tuple
    campo_estado: str | None = "activo"
    se_crea: bool = True
    orden: tuple = field(default_factory=tuple)

    def ruta(self, accion):
        return f"maestros:{self.clave}_{accion}"

    @property
    def nuevo(self):
        return f"{'Nueva' if self.articulo == 'la' else 'Nuevo'} {self.singular}"


def _si_no(valor):
    return "Sí" if valor else "No"


CATALOGOS = {
    c.clave: c
    for c in (
        Catalogo(
            clave="ubicacion",
            ruta_base="ubicaciones",
            articulo="la",
            singular="ubicación",
            plural="Ubicaciones y puntos de venta",
            descripcion="Zonas de la bodega y puntos de venta. Abrir un PDV nuevo no exige "
            "cambiar el sistema (RF-06).",
            icono="vitrina",
            modelo=Ubicacion,
            formulario=UbicacionForm,
            busqueda=("codigo__icontains", "nombre__icontains"),
            columnas=(
                Columna("Código", lambda o: o.codigo, "codigo"),
                Columna("Nombre", lambda o: o.nombre),
                Columna("Tipo", lambda o: o.get_tipo_display()),
            ),
            orden=("tipo", "codigo"),
        ),
        Catalogo(
            clave="categoria",
            ruta_base="categorias",
            articulo="la",
            singular="categoría",
            plural="Categorías de producto",
            descripcion="Agrupan los productos del catálogo.",
            icono="productos",
            modelo=CategoriaProducto,
            formulario=CategoriaForm,
            busqueda=("nombre__icontains",),
            columnas=(
                Columna("Nombre", lambda o: o.nombre),
                Columna(
                    "Productos activos", lambda o: o.productos.filter(activo=True).count(), "num"
                ),
            ),
            campo_estado="activa",
            orden=("nombre",),
        ),
        Catalogo(
            clave="cliente",
            ruta_base="clientes",
            articulo="el",
            singular="cliente",
            plural="Clientes",
            descripcion="Mayoristas y restaurantes, con su autorización de datos (Ley 1581).",
            icono="pedidos",
            modelo=Cliente,
            formulario=ClienteForm,
            busqueda=("razon_social__icontains", "numero_documento__icontains"),
            columnas=(
                Columna("Razón social", lambda o: o.razon_social),
                Columna(
                    "Documento", lambda o: f"{o.tipo_documento} {o.numero_documento}", "codigo"
                ),
                Columna(
                    "Autorización de datos",
                    lambda o: (
                        f"Sí, {o.fecha_autorizacion:%d/%m/%Y}"
                        if o.autoriza_tratamiento_datos and o.fecha_autorizacion
                        else _si_no(o.autoriza_tratamiento_datos)
                    ),
                ),
            ),
            orden=("razon_social",),
        ),
        Catalogo(
            clave="proveedor",
            ruta_base="proveedores",
            articulo="el",
            singular="proveedor",
            plural="Proveedores",
            descripcion="Quienes entregan producto en la recepción.",
            icono="recepcion",
            modelo=Proveedor,
            formulario=ProveedorForm,
            busqueda=("razon_social__icontains", "numero_documento__icontains"),
            columnas=(
                Columna("Razón social", lambda o: o.razon_social),
                Columna(
                    "Documento", lambda o: f"{o.tipo_documento} {o.numero_documento}", "codigo"
                ),
            ),
            orden=("razon_social",),
        ),
        Catalogo(
            clave="embalaje",
            ruta_base="embalajes",
            articulo="el",
            singular="tipo de embalaje",
            plural="Tipos de embalaje",
            descripcion="Canastillas y cajas con su tara. La tara cero es el producto sin "
            "embalaje (RF-08). Cambiarla solo afecta las pesadas nuevas.",
            icono="embultaje",
            modelo=TipoEmbalaje,
            formulario=EmbalajeForm,
            busqueda=("nombre__icontains",),
            columnas=(
                Columna("Nombre", lambda o: o.nombre),
                Columna("Tara", lambda o: f"{o.peso_tara} kg", "num"),
            ),
            orden=("nombre",),
        ),
        Catalogo(
            clave="parametro",
            ruta_base="parametros",
            articulo="el",
            singular="parámetro",
            plural="Parámetros del sistema",
            descripcion="Valores que el sistema interpreta, como la tolerancia de balance de "
            "masa de la transformación (RF-27). Se validan al guardarlos.",
            icono="configuracion",
            modelo=Parametro,
            formulario=ParametroValorForm,
            busqueda=("clave__icontains", "descripcion__icontains"),
            columnas=(
                Columna("Clave", lambda o: o.clave, "codigo"),
                Columna("Valor", lambda o: o.valor, "codigo"),
                Columna("Descripción", lambda o: o.descripcion or ""),
            ),
            campo_estado=None,
            se_crea=False,
            orden=("clave",),
        ),
    )
}
