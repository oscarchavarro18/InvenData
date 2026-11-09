"""Navegación de la interfaz según el perfil (RF-02, RN-04 a RN-08).

Un solo lugar decide qué módulos ve cada persona y cuál está activo. De aquí salen el menú
superior del escritorio, el cajón «Más» del celular, la barra inferior, la hoja «Registrar»
y el buscador rápido (Ctrl K), así ninguna de esas piezas muestra algo que el perfil no
puede abrir. Solo arma enlaces: los permisos de verdad los siguen haciendo cumplir las vistas.
"""

from dataclasses import dataclass, field

from django.urls import reverse

from apps.maestros.catalogos import CATALOGOS

# Cambia en cada entrega de la interfaz: obliga al navegador a pedir el CSS y el JS nuevos
# en lugar de usar los que guardó en caché. En producción, WhiteNoise ya pone un hash.
VERSION_ESTATICOS = "2026.11.7"


@dataclass
class Item:
    nombre: str
    url: str
    icono: str
    activo: bool = False
    descripcion: str = ""

    @property
    def corto(self):
        """Nombre para la barra inferior del celular, que solo tiene una línea por acceso."""
        return CORTOS.get(self.nombre, self.nombre)


CORTOS = {"Existencia PDV": "Existencia", "Traslados a PDV": "Traslados", "Conteo físico": "Conteo"}


@dataclass
class Grupo:
    nombre: str
    items: list = field(default_factory=list)

    @property
    def activo(self):
        return any(item.activo for item in self.items)


def _ruta(request):
    """Espacio de nombres y nombre de la vista actual, o vacíos si no hay coincidencia."""
    coincidencia = getattr(request, "resolver_match", None)
    if coincidencia is None:
        return "", ""
    return coincidencia.namespace or "", coincidencia.url_name or ""


def _grupos(usuario, espacio, vista):
    """Los grupos del menú con sus módulos, en el orden en que trabaja la operación."""
    en = espacio.__eq__
    bodega = Grupo("Bodega")
    salidas = Grupo("Salidas")
    puntos = Grupo("Puntos de venta")
    control = Grupo("Control")

    if usuario.ve_bodega:
        bodega.items += [
            Item(
                "Recepción",
                reverse("recepcion:documento_lista"),
                "recepcion",
                en("recepcion"),
                "Documentos del proveedor, pesadas y cierre",
            ),
            Item(
                "Inventario",
                reverse("inventario:existencias"),
                "inventario",
                en("inventario"),
                "Existencias por lote y zona",
            ),
            Item(
                "Transformación",
                reverse("transformacion:orden_lista"),
                "transformacion",
                en("transformacion"),
                "Órdenes de corte y reempaque",
            ),
            Item(
                "Embultaje",
                reverse("embultaje:documento_lista"),
                "embultaje",
                en("embultaje") and not vista.startswith("pedido"),
                "Bultos del día",
            ),
            Item(
                "Pedidos",
                reverse("embultaje:pedido_lista"),
                "pedidos",
                en("embultaje") and vista.startswith("pedido"),
                "Pedidos de mayoristas y FIFO",
            ),
        ]
        salidas.items += [
            Item(
                "Despachos",
                reverse("despacho:despacho_lista"),
                "despacho",
                en("despacho") and not vista.startswith("traslado"),
                "Ventas a mayoristas",
            ),
            Item(
                "Traslados a PDV",
                reverse("despacho:traslado_lista"),
                "traslado",
                en("despacho") and vista.startswith("traslado"),
                "Envíos a los puntos de venta",
            ),
        ]
    if usuario.es_admin_pdv:
        puntos.items.append(
            Item(
                "Traslados recibidos",
                reverse("despacho:traslado_lista"),
                "traslado",
                en("despacho"),
                "Verificar, aceptar o rechazar",
            )
        )
    if usuario.ve_algun_punto_venta:
        puntos.items += [
            Item(
                "Ventas",
                reverse("puntoventa:venta_lista"),
                "ventas",
                en("puntoventa") and vista.startswith("venta"),
                "Consumidor final y restaurantes",
            ),
            Item(
                "Existencia PDV",
                reverse("puntoventa:existencias"),
                "vitrina",
                en("puntoventa") and vista == "existencias",
                "Lo que hay en vitrina",
            ),
            Item(
                "Historial PDV",
                reverse("puntoventa:historial"),
                "historial",
                en("puntoventa") and vista == "historial",
                "Entradas y salidas del punto",
            ),
        ]
    if usuario.ve_bodega or usuario.ve_algun_punto_venta:
        control.items += [
            Item(
                "Conteo físico",
                reverse("conteo:conteo_lista"),
                "conteo",
                en("conteo"),
                "Conteos, ajustes y reversos",
            ),
            Item(
                "Inventario inicial",
                reverse("levantamiento:levantamiento_lista"),
                "arranque",
                en("levantamiento"),
                "Levantamiento por ubicación",
            ),
        ]
    if not usuario.es_gerente:
        # El Gerente administra los productos desde Administración; los demás los consultan.
        control.items.append(
            Item(
                "Productos",
                reverse("maestros:producto_lista"),
                "productos",
                en("maestros") and vista.startswith("producto"),
                "Catálogo de productos",
            )
        )
    administracion = Grupo("Administración")
    if usuario.es_gerente:
        administracion.items = _administracion(en, vista)
    return [g for g in (bodega, salidas, puntos, control, administracion) if g.items]


def _administracion(en, vista):
    """Los maestros, los usuarios y la auditoría: control total, solo del Gerente (RF-02)."""
    items = [
        Item(
            "Resumen",
            reverse("maestros:administracion"),
            "configuracion",
            en("maestros") and vista == "administracion",
            "Todos los maestros de un vistazo",
        ),
        Item(
            "Usuarios",
            reverse("accounts:usuario_lista"),
            "usuarios",
            en("accounts"),
            "Accesos, perfiles y contraseñas",
        ),
        Item(
            "Productos",
            reverse("maestros:producto_lista"),
            "productos",
            en("maestros") and vista.startswith("producto"),
            "Catálogo, edición y estado",
        ),
    ]
    for catalogo in CATALOGOS.values():
        items.append(
            Item(
                catalogo.plural,
                reverse(catalogo.ruta("lista")),
                catalogo.icono,
                en("maestros") and vista.startswith(f"{catalogo.clave}_"),
                catalogo.descripcion.split(".")[0],
            )
        )
    items.append(
        Item(
            "Auditoría",
            reverse("auditoria:auditoria_lista"),
            "auditoria",
            en("auditoria"),
            "Quién hizo qué y cuándo",
        )
    )
    return items


def _acciones(usuario):
    """Lo que la persona puede registrar desde el botón «Registrar»."""
    acciones = []
    if usuario.puede_operar_recepcion:
        acciones.append(
            Item(
                "Recepción",
                reverse("recepcion:documento_crear"),
                "recepcion",
                descripcion="Nuevo documento del proveedor",
            )
        )
    if usuario.puede_operar_bodega:
        acciones += [
            Item(
                "Mover o transformar",
                reverse("inventario:existencias"),
                "inventario",
                descripcion="Traslado, transformación o embultaje de un lote",
            ),
            Item(
                "Pedido",
                reverse("embultaje:pedido_crear"),
                "pedidos",
                descripcion="Pedido de un cliente mayorista",
            ),
            Item(
                "Traslado a PDV",
                reverse("despacho:traslado_crear"),
                "traslado",
                descripcion="Enviar producto a un punto de venta",
            ),
        ]
    if usuario.es_gerente or usuario.es_admin_pdv:
        acciones += [
            Item(
                "Venta",
                reverse("puntoventa:venta_nueva", args=["consumidor"]),
                "ventas",
                descripcion="A consumidor final, con factura de Siigo",
            ),
            Item(
                "Remisión",
                reverse("puntoventa:venta_nueva", args=["restaurante"]),
                "ventas",
                descripcion="Venta a un restaurante",
            ),
        ]
    if usuario.puede_operar_bodega or usuario.es_admin_pdv:
        acciones.append(
            Item(
                "Conteo físico",
                reverse("conteo:conteo_nuevo"),
                "conteo",
                descripcion="Jornada de conteo de una ubicación",
            )
        )
    return acciones


def navegacion(request):
    """Procesador de contexto: la navegación de quien tiene sesión, o solo la versión."""
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {"version_estaticos": VERSION_ESTATICOS}
    espacio, vista = _ruta(request)
    grupos = _grupos(usuario, espacio, vista)
    inicio = Item("Inicio", reverse("inicio"), "inicio", espacio == "" and vista == "inicio")
    reportes = None
    if usuario.ve_bodega or usuario.ve_algun_punto_venta:
        reportes = Item(
            "Reportes",
            reverse("reportes:indice"),
            "reportes",
            espacio == "reportes",
            "Informes, trazabilidad e indicadores",
        )
    todos = [item for grupo in grupos for item in grupo.items]

    # Barra inferior del celular: los cuatro accesos que más se usan según el perfil.
    def primero(*nombres):
        return next((i for n in nombres for i in todos if i.nombre == n), None)

    segundo = primero("Inventario", "Existencia PDV", "Productos")
    cuarto = primero("Ventas", "Despachos", "Conteo físico") or reportes
    acciones = _acciones(usuario)
    return {
        "version_estaticos": VERSION_ESTATICOS,
        "nav": {
            "inicio": inicio,
            "grupos": grupos,
            "reportes": reportes,
            "barra": [i for i in (segundo, cuarto) if i],
            "acciones": acciones,
            "buscables": [inicio, *todos, *([reportes] if reportes else []), *acciones],
            "iniciales": "".join(p[0] for p in usuario.nombre_completo.split()[:2]).upper()
            or usuario.usuario[:1].upper(),
        },
    }
