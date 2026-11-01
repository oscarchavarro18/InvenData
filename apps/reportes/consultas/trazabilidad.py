"""Trazabilidad de punta a punta de un lote (RF-54, RF-22, RF-28).

Reconstruye el recorrido completo: de qué documento de proveedor vino (o de qué orden de
transformación o levantamiento), en qué tandas se pesó, si se transformó o se embultó, y en
qué despacho o traslado salió de la bodega. La venta en el punto de venta ya no se ata al
lote: allí el control es por producto (SN-09), así que el recorrido del lote termina al
entrar al punto de venta.
"""

from django.db.models import Sum
from django.utils import timezone

from apps.despacho.models import DespachoDetalle
from apps.inventario.consultas import historial_de_lote
from apps.inventario.models import Lote, Movimiento, TipoMovimiento
from apps.reportes.consultas.clasificacion import ENTRADA, MERMA, TRASLADO, clase_bodega
from apps.reportes.consultas.comun import CERO
from apps.reportes.reporte import Columna, Reporte, Seccion, formatear
from apps.transformacion.models import EstadoOrden

DATO = [Columna("dato", "Dato"), Columna("valor", "Valor")]


def _dato(dato, valor):
    return {"dato": dato, "valor": valor if valor not in (None, "") else "-"}


def _kg(valor):
    return f"{formatear(valor, 'kg')} kg" if valor is not None else None


def _origen(lote):
    """De dónde salió el lote: recepción, transformación o inventario inicial."""
    datos = [
        _dato("Lote", lote.codigo),
        _dato("Producto", f"{lote.producto.codigo} · {lote.producto.nombre}"),
        _dato("Estado del producto", lote.get_estado_producto_display()),
        _dato("Vence", lote.fecha_vencimiento.strftime("%d/%m/%Y")),
        _dato("Estado del lote", lote.get_estado_display()),
        _dato("Origen", lote.get_origen_display()),
    ]
    linea = lote.documento_proveedor_linea
    if linea is not None:
        documento = linea.documento_proveedor
        datos += [
            _dato("Proveedor", documento.proveedor.razon_social),
            _dato(
                "Documento del proveedor",
                f"{documento.get_tipo_documento_display()} {documento.numero_documento} "
                f"del {documento.fecha:%d/%m/%Y} ({documento.get_estado_display().lower()})",
            ),
            _dato("Declarado en la línea", _kg(linea.cantidad)),
            _dato("Recibido en la línea", _kg(linea.cantidad_recibida)),
            _dato("Merma de recepción de la línea", _kg(linea.diferencia_kg)),
        ]
    registro = lote.registros_transformacion.select_related("orden__lote_origen").first()
    if registro is not None:
        orden = registro.orden
        datos += [
            _dato("Orden de transformación", orden.consecutivo),
            _dato("Lote de origen", orden.lote_origen.codigo),
            _dato("Fecha de la orden", timezone.localtime(orden.fecha_hora).strftime("%d/%m/%Y")),
        ]
    levantamiento = lote.levantamiento.select_related("inventario_inicial__ubicacion").first()
    if levantamiento is not None:
        inicial = levantamiento.inventario_inicial
        datos.append(
            _dato(
                "Levantamiento inicial",
                f"{inicial.ubicacion.nombre}, {inicial.fecha:%d/%m/%Y}",
            )
        )
    if lote.cerrado_en:
        datos += [
            _dato("Total embultado", _kg(lote.total_embultado_kg)),
            _dato("Merma de embultaje", _kg(lote.merma_vs_origen_kg)),
            _dato(
                "Cerrado como embultado",
                timezone.localtime(lote.cerrado_en).strftime("%d/%m/%Y %H:%M"),
            ),
        ]
    return datos


def _tandas(lote):
    filas = []
    for t in lote.tandas.select_related("tipo_embalaje", "ubicacion_destino", "responsable"):
        neto = t.peso_neto
        filas.append(
            {
                "fecha": t.fecha_hora,
                "ubicacion": t.ubicacion_destino.nombre,
                "embalaje": t.tipo_embalaje.nombre,
                "cantidad": t.cantidad_embalajes,
                "bruto": t.peso_bruto,
                "tara": (t.peso_bruto - neto) if neto is not None else None,
                "neto": neto,
                "temperatura": f"{t.temperatura} °C",
                "responsable": t.responsable.nombre_completo,
            }
        )
    return filas


def _transformaciones(lote):
    filas = []
    ordenes = lote.ordenes_transformacion.filter(estado=EstadoOrden.CONFIRMADA).prefetch_related(
        "derivados__lote_derivado"
    )
    for orden in ordenes.order_by("fecha_hora"):
        filas.append(
            {
                "orden": orden.consecutivo,
                "fecha": orden.fecha_hora,
                "consumido": orden.cantidad_consumida,
                "salida": orden.masa_salida,
                "merma": orden.merma_kg,
                "cierre": orden.porcentaje_cierre,
                "tolerancia": "Sí" if orden.dentro_tolerancia else "No",
                "derivados": ", ".join(
                    f"{d.lote_derivado.codigo} ({d.cantidad} kg)" for d in orden.derivados.all()
                ),
            }
        )
    return filas


def _embultajes(lote):
    filas = []
    registros = lote.registros_embultaje.select_related(
        "ubicacion_origen", "ubicacion_destino", "usuario"
    ).prefetch_related("bultos")
    for r in registros.order_by("fecha_hora"):
        bultos = sorted(b.consecutivo for b in r.bultos.all())
        filas.append(
            {
                "fecha": r.fecha_hora,
                "ruta": f"{r.ubicacion_origen.nombre} > {r.ubicacion_destino.nombre}",
                "bultos": r.cantidad_bultos,
                "consecutivos": f"{bultos[0]} a {bultos[-1]}" if bultos else "",
                "kg": r.total_kilos,
                "usuario": r.usuario.nombre_completo,
            }
        )
    return filas


def _despachos(lote):
    filas = []
    detalles = DespachoDetalle.objects.filter(alistamiento_detalle__lote=lote).select_related(
        "despacho_mayorista__pedido__cliente"
    )
    for d in detalles.order_by("despacho_mayorista__fecha_hora"):
        despacho = d.despacho_mayorista
        filas.append(
            {
                "fecha": despacho.fecha_hora,
                "documento": f"{despacho.get_tipo_documento_display()} {despacho.numero_documento}",
                "pedido": despacho.pedido.consecutivo,
                "cliente": despacho.pedido.cliente.razon_social,
                "vehiculo": f"{despacho.placa_vehiculo.upper()} · {despacho.nombre_conductor}",
                "bultos": d.cantidad_bultos_cajas,
                "kg": d.cantidad,
                "recibio": despacho.nombre_recibe or "Sin constancia",
            }
        )
    return filas


def _traslados(lote):
    filas = []
    detalles = lote.traslados_pdv.select_related("traslado_pdv__ubicacion_destino")
    for d in detalles.order_by("traslado_pdv__fecha_hora"):
        traslado = d.traslado_pdv
        filas.append(
            {
                "fecha": traslado.fecha_hora,
                "traslado": traslado.consecutivo,
                "destino": traslado.ubicacion_destino.nombre,
                "estado": traslado.get_estado_display(),
                "kg": d.cantidad,
                "verificado": d.cantidad_verificada,
                "confirmado": traslado.fecha_hora_confirmacion,
            }
        )
    return filas


def _recorrido(lote):
    filas = []
    for m in historial_de_lote(lote):
        origen = m.ubicacion_origen.nombre if m.ubicacion_origen else ""
        destino = m.ubicacion_destino.nombre if m.ubicacion_destino else ""
        marca = ""
        if m.movimiento_reversado_id:
            marca = "Reverso"
        elif m.reversado:
            marca = "Reversado"
        filas.append(
            {
                "fecha": m.fecha_hora,
                "tipo": m.get_tipo_display(),
                "ruta": " > ".join(u for u in (origen, destino) if u),
                "kg": m.cantidad,
                "marca": marca,
                "usuario": m.usuario.nombre_completo,
                "observacion": m.observacion or "",
            }
        )
    return filas


# Cómo se rotula cada destino del lote en su balance.
_CONCEPTOS = {
    TipoMovimiento.RECEPCION: "Ingresó por recepción",
    TipoMovimiento.INVENTARIO_INICIAL: "Ingresó por inventario inicial",
    TipoMovimiento.PRODUCCION_TRANSFORMACION: "Ingresó por transformación",
    TipoMovimiento.CONSUMO_TRANSFORMACION: "Consumido en transformación",
    TipoMovimiento.DESPACHO_MAYORISTA: "Despachado a mayoristas",
    TipoMovimiento.TRASLADO_PDV: "Trasladado a puntos de venta",
    TipoMovimiento.MERMA_EMBULTAJE: "Merma de embultaje",
}


def balance_del_lote(lote):
    """Cuánto entró, a dónde salió, cuánto se perdió y cuánto queda (en bodega)."""
    conceptos = {}
    movimientos = Movimiento.objects.filter(lote=lote).values(
        "tipo", "motivo_ajuste", "ubicacion_origen", "ubicacion_destino"
    )
    for g in movimientos.annotate(kg=Sum("cantidad")).order_by():
        tipo, clase = g["tipo"], clase_bodega(g["tipo"], g["motivo_ajuste"])
        if clase == TRASLADO and tipo != TipoMovimiento.TRASLADO_PDV:
            continue  # moverse entre zonas no cambia lo que tiene el lote
        if tipo == TipoMovimiento.AJUSTE_CONTEO:
            suma = g["ubicacion_destino"] is not None
            concepto = "Pérdidas y vencimientos" if clase == MERMA else "Ajustes"
            signo = 1 if suma else -1
        else:
            concepto = _CONCEPTOS[tipo]
            signo = 1 if clase == ENTRADA else -1
        conceptos[concepto] = conceptos.get(concepto, CERO) + signo * g["kg"]
    filas = [{"concepto": c, "kg": kg} for c, kg in conceptos.items() if kg]
    orden = [*_CONCEPTOS.values(), "Pérdidas y vencimientos", "Ajustes"]
    filas.sort(key=lambda f: orden.index(f["concepto"]))
    queda = lote.existencias.aggregate(t=Sum("cantidad"))["t"] or CERO
    calculado = sum((f["kg"] for f in filas), CERO)
    return filas, queda, calculado


def trazabilidad(lote):
    """El recorrido completo de un lote, listo para pantalla, CSV y PDF (RF-54)."""
    # Se relee: el estado, el cierre y la merma de embultaje pueden haber cambiado.
    lote = Lote.objects.select_related(
        "producto", "documento_proveedor_linea__documento_proveedor__proveedor"
    ).get(pk=lote.pk)
    balance, queda, calculado = balance_del_lote(lote)
    ingresado = sum((f["kg"] for f in balance if f["kg"] > 0), CERO)

    def total(concepto):
        return -sum((f["kg"] for f in balance if f["concepto"] == concepto), CERO)

    perdido = total("Merma de embultaje") + total("Pérdidas y vencimientos")
    primero = lote.movimientos.order_by("fecha_hora").values_list("fecha_hora", flat=True).first()
    if primero is None:
        dias = None
    else:
        ultimo = timezone.now()
        if not queda:
            ultimo = (
                lote.movimientos.order_by("-fecha_hora")
                .values_list("fecha_hora", flat=True)
                .first()
            )
        dias = (timezone.localtime(ultimo).date() - timezone.localtime(primero).date()).days

    tandas = _tandas(lote)
    derivados = [
        {"lote": d.codigo, "producto": d.producto.nombre, "estado": d.get_estado_display()}
        for d in lote.derivados.select_related("producto").order_by("codigo")
    ]
    secciones = [
        Seccion("Identificación y origen", DATO, _origen(lote)),
        Seccion(
            "Tandas de pesaje",
            [
                Columna("fecha", "Fecha y hora", "fechahora"),
                Columna("ubicacion", "Ubicación"),
                Columna("embalaje", "Embalaje"),
                Columna("cantidad", "Embalajes", "entero"),
                Columna("bruto", "Peso bruto", "kg"),
                Columna("tara", "Tara", "kg"),
                Columna("neto", "Peso neto", "kg"),
                Columna("temperatura", "Temperatura"),
                Columna("responsable", "Responsable"),
            ],
            tandas,
            {
                "fecha": "Total",
                "bruto": sum((t["bruto"] for t in tandas), CERO),
                "neto": sum((t["neto"] or CERO for t in tandas), CERO),
            }
            if tandas
            else {},
        ),
        Seccion(
            "Transformaciones en que se consumió",
            [
                Columna("orden", "Orden"),
                Columna("fecha", "Fecha y hora", "fechahora"),
                Columna("consumido", "Consumido", "kg"),
                Columna("salida", "Salida", "kg"),
                Columna("merma", "Merma", "kg"),
                Columna("cierre", "% de cierre", "porcentaje"),
                Columna("tolerancia", "Dentro de tolerancia"),
                Columna("derivados", "Lotes derivados"),
            ],
            _transformaciones(lote),
        ),
        Seccion(
            "Lotes derivados",
            [
                Columna("lote", "Lote"),
                Columna("producto", "Producto"),
                Columna("estado", "Estado"),
            ],
            derivados,
            nota="Cada derivado tiene su propia trazabilidad, que apunta a este lote (RF-28).",
        ),
        Seccion(
            "Embultaje",
            [
                Columna("fecha", "Fecha y hora", "fechahora"),
                Columna("ruta", "De > a"),
                Columna("bultos", "Bultos", "entero"),
                Columna("consecutivos", "Consecutivos"),
                Columna("kg", "Kg", "kg"),
                Columna("usuario", "Registró"),
            ],
            _embultajes(lote),
        ),
        Seccion(
            "Despachos a mayoristas",
            [
                Columna("fecha", "Fecha y hora", "fechahora"),
                Columna("documento", "Documento"),
                Columna("pedido", "Pedido"),
                Columna("cliente", "Cliente"),
                Columna("vehiculo", "Vehículo y conductor"),
                Columna("bultos", "Bultos o cajas", "entero"),
                Columna("kg", "Kg", "kg"),
                Columna("recibio", "Recibió"),
            ],
            _despachos(lote),
        ),
        Seccion(
            "Traslados a puntos de venta",
            [
                Columna("fecha", "Enviado", "fechahora"),
                Columna("traslado", "Traslado"),
                Columna("destino", "Punto de venta"),
                Columna("estado", "Estado"),
                Columna("kg", "Kg enviados", "kg"),
                Columna("verificado", "Kg verificados", "kg"),
                Columna("confirmado", "Aceptado o rechazado", "fechahora"),
            ],
            _traslados(lote),
            nota=(
                "Al aceptarse, el producto pasa al punto de venta, donde se controla por "
                "producto y no por lote (SN-09): allí termina el recorrido del lote."
            ),
        ),
        Seccion(
            "Recorrido cronológico",
            [
                Columna("fecha", "Fecha y hora", "fechahora"),
                Columna("tipo", "Movimiento"),
                Columna("ruta", "De > a"),
                Columna("kg", "Kg", "kg"),
                Columna("marca", "Corrección"),
                Columna("usuario", "Registró"),
                Columna("observacion", "Observación"),
            ],
            _recorrido(lote),
        ),
        Seccion(
            "Balance del lote",
            [Columna("concepto", "Concepto"), Columna("kg", "Kg (+ entra, - sale)", "kg")],
            balance,
            {"concepto": "Queda en bodega (calculado)", "kg": calculado} if balance else {},
            nota=(
                f"Existencia registrada hoy: {queda} kg. "
                + (
                    "Cuadra con el libro de movimientos."
                    if calculado == queda
                    else "No cuadra con el libro de movimientos: revise los ajustes."
                )
            ),
        ),
    ]
    return Reporte(
        titulo=f"Trazabilidad del lote {lote.codigo}",
        archivo=f"trazabilidad-{lote.codigo}",
        columnas=[],
        filtros=[("Lote", lote.codigo), ("Producto", lote.producto.nombre)],
        resumen=[
            ("Ingresó", ingresado, "kg"),
            ("Consumido en transformación", total("Consumido en transformación"), "kg"),
            ("Despachado", total("Despachado a mayoristas"), "kg"),
            ("Trasladado a PDV", total("Trasladado a puntos de venta"), "kg"),
            ("Perdido", perdido, "kg"),
            ("Queda en bodega", queda, "kg"),
            ("Días en bodega", dias, "entero"),
            ("Situación", "Agotado" if not queda else "Con existencia", "texto"),
        ],
        secciones=secciones,
        nota="Generado desde el libro de movimientos, que nunca se edita ni se borra (RNF-03).",
    )
