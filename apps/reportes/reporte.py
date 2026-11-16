"""La forma común de todos los reportes (RF-66, RN-40).

Cada consulta arma un `Reporte`: título, filtros aplicados, cifras clave, columnas, filas y
totales. Con esa misma estructura se dibuja la tabla en pantalla y se exporta a CSV y a PDF,
así ningún reporte tiene su propia exportación y todos se ven y se descargan igual.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

# Cómo se muestra y se alinea cada tipo de dato.
NUMERICOS = {"kg", "entero", "porcentaje", "dias"}


@dataclass(frozen=True)
class Columna:
    clave: str
    titulo: str
    tipo: str = "texto"  # texto, kg, entero, porcentaje, dias, fecha, fechahora

    @property
    def numerica(self):
        return self.tipo in NUMERICOS


@dataclass
class Seccion:
    """Una tabla con título dentro de un reporte de varias partes (trazabilidad, informe)."""

    titulo: str
    columnas: list
    filas: list = field(default_factory=list)
    totales: dict = field(default_factory=dict)
    nota: str = ""

    def celdas(self, fila):
        return [formatear(fila.get(c.clave), c.tipo) for c in self.columnas]

    def fila_de_totales(self):
        if not self.totales:
            return None
        celdas = [formatear(self.totales.get(c.clave), c.tipo) for c in self.columnas]
        celdas[0] = celdas[0] or "Total"
        return celdas


@dataclass
class Reporte:
    titulo: str
    columnas: list
    filas: list = field(default_factory=list)  # diccionarios por clave de columna
    filtros: list = field(default_factory=list)  # [(etiqueta, valor)] para el encabezado
    resumen: list = field(default_factory=list)  # [(etiqueta, valor, tipo)] cifras clave
    totales: dict = field(default_factory=dict)  # por clave de columna
    nota: str = ""
    archivo: str = "reporte"  # nombre base de los archivos descargados
    generado: datetime = field(default_factory=timezone.now)
    # Reportes de varias partes: sin `columnas` propias, todo va en secciones.
    secciones: list = field(default_factory=list)

    @property
    def tablas(self):
        """Todas las tablas en orden: la principal (si tiene columnas) y las secciones."""
        principal = []
        if self.columnas:
            principal = [Seccion("", self.columnas, self.filas, self.totales)]
        return principal + list(self.secciones)

    def celdas(self, fila):
        """Los valores de una fila ya formateados, en el orden de las columnas."""
        return [formatear(fila.get(c.clave), c.tipo) for c in self.columnas]

    def fila_de_totales(self):
        if not self.totales:
            return None
        celdas = [formatear(self.totales.get(c.clave), c.tipo) for c in self.columnas]
        celdas[0] = celdas[0] or "Total"
        return celdas


def _miles(entero):
    """1234567 → '1.234.567' (separador de miles de Colombia)."""
    return f"{entero:,}".replace(",", ".")


def numero(valor, decimales=2, miles=True):
    """Decimal en formato colombiano: coma decimal y punto de miles."""
    valor = Decimal(valor).quantize(Decimal(1).scaleb(-decimales))
    signo = "-" if valor < 0 else ""
    entero, _, fraccion = f"{abs(valor):.{decimales}f}".partition(".")
    entero = _miles(int(entero)) if miles else entero
    return f"{signo}{entero},{fraccion}" if decimales else f"{signo}{entero}"


def formatear(valor, tipo, miles=True):
    """Texto para pantalla y PDF. En el CSV se usa sin miles para que Excel lo lea."""
    if valor is None or valor == "":
        return ""
    if tipo == "kg":
        return numero(valor, 2, miles)
    if tipo == "porcentaje":
        return f"{numero(valor, 1, miles)} %"
    if tipo == "dias":
        return numero(valor, 1, miles)
    if tipo == "entero":
        return _miles(int(valor)) if miles else str(int(valor))
    if tipo == "fechahora" and isinstance(valor, datetime):
        return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")
    if tipo == "fecha" and isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)
