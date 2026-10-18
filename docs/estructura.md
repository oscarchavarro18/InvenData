# Estructura del proyecto

    invendata/
    |-- config/              Configuración de Django (settings por entorno: base, dev, test, prod)
    |-- apps/                Una aplicación por módulo funcional
    |-- templates/ static/   Interfaz (Bootstrap 5)
    |-- requirements/        base.txt, dev.txt, prod.txt
    |-- docker/              Script de arranque del contenedor web
    |-- docs/                Convenciones del equipo
    |-- Makefile             Atajos de desarrollo (make up, make test, make lint...)
    `-- .github/             CI, plantilla de PR y Dependabot

## Aplicaciones, módulos y tablas del Diccionario de datos

| App | Módulo | Tablas |
|---|---|---|
| `core` | Transversal | Modelos base (ModeloBase, ModeloCreacion), verificación de salud, página de inicio |
| `accounts` | M1 | perfil, usuario ✔ |
| `maestros` | M1 | ubicacion, proveedor, cliente, categoria_producto, producto, tipo_embalaje, parametro ✔ |
| `auditoria` | M1 | auditoria, evidencia ✔ |
| `levantamiento` | M0 | inventario_inicial, inventario_inicial_detalle_lote, inventario_inicial_detalle_producto |
| `recepcion` | M2 | documento_proveedor ✔, documento_proveedor_linea ✔, recepcion |
| `inventario` | M3 | lote, movimiento, existencia ✔ |
| `transformacion` | M4 | orden_transformacion, transformacion_derivado |
| `embultaje` | M5 | documento_embultaje, embultaje_registro, bulto, pedido, pedido_linea, alistamiento_detalle |
| `despacho` | M6 | despacho_mayorista, despacho_detalle, traslado_pdv, traslado_pdv_detalle, traslado_pdv_observacion |
| `puntoventa` | M7 | movimiento_punto_venta, existencia_punto_venta, venta_consumidor_final (+línea), venta_restaurante_remision (+línea) |
| `conteo` | M8 | conteo_fisico, conteo_fisico_detalle |
| `reportes` | M9 | (sin tablas: consulta lo anterior) |

✔ = implementada. Total del modelo: 41 tablas. Implementadas hasta ahora: 16 (M1 completo: perfil, usuario, los maestros, auditoria y evidencia; M3 núcleo: lote, movimiento y existencia; M2 en curso: documento_proveedor y documento_proveedor_linea).

## Convenciones

- `db_table` igual al nombre de la tabla del Diccionario.
- Los CHECK del modelo se implementan como `CheckConstraint`; las reglas "validar en la aplicación" en `clean()` o en la capa de servicios del módulo.
- Claves foráneas con `on_delete=PROTECT` en todo lo histórico (nada se borra; RNF-06).
- Las correcciones de inventario se hacen con movimientos inversos, nunca editando (RF-09), y solo el Gerente las registra.
- El inventario solo se mueve con `registrar_movimiento` (apps/inventario/servicios.py): una sola transacción registra el movimiento y actualiza la existencia, que nunca queda negativa.
- Los perfiles (Gerente, Jefe de bodega, Administrador de PDV, Consulta) son datos de referencia cargados por migración.
