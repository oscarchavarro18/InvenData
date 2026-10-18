import argparse
import json
import subprocess
import sys
import shutil

PROJECT_TITLE = "InvenData — Tablero de control"

# Node-id (GraphQL) del proyecto, se completa en main() y lo usa
# create_issues_and_add_to_board() para mover cada tarjeta a "Backlog".
_project_node_id = None

# ---------------------------------------------------------------------------
# Utilidades para invocar `gh`
# ---------------------------------------------------------------------------

def run(args, input_text=None, check=True):
    result = subprocess.run(
        args, capture_output=True, text=True, input=input_text
    )
    if check and result.returncode != 0:
        print(f"\n✗ Falló: {' '.join(args)}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result


def gh(*args, check=True):
    return run(["gh", *args], check=check)


def gh_json(*args):
    r = gh(*args)
    out = r.stdout.strip()
    return json.loads(out) if out else None


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(owner, repo):
    if shutil.which("gh") is None:
        print("✗ No encuentro `gh` (GitHub CLI). Instálalo en WSL con: sudo apt install gh -y)
        sys.exit(1)

    r = gh("auth", "status", check=False)
    if r.returncode != 0:
        print("✗ No has iniciado sesión en gh. Corre: gh auth login")
        sys.exit(1)

    # Projects v2 necesita el scope "project" además del token normal.
    r = gh("project", "list", "--owner", owner, "--format", "json", check=False)
    if r.returncode != 0:
        print("✗ No tengo permiso para leer Projects (v2) de esa cuenta.")
        print("  Corre esto una vez y vuelve a intentar:")
        print("    gh auth refresh -s project,read:project")
        sys.exit(1)

    print(f"✓ gh instalado y autenticado. Repositorio: {owner}/{repo}")


def detect_owner_repo(args):
    if args.owner and args.repo:
        return args.owner, args.repo
    r = gh("repo", "view", "--json", "owner,name", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        print("✗ No pude detectar el repositorio automáticamente.")
        print("  Párate dentro de la carpeta del repo, o pasa --owner y --repo.")
        sys.exit(1)
    data = json.loads(r.stdout)
    owner = args.owner or data["owner"]["login"]
    repo = args.repo or data["name"]
    return owner, repo


# ---------------------------------------------------------------------------
# 1. Labels
# ---------------------------------------------------------------------------

LABELS = [
    # tipo de trabajo
    ("tipo:desarrollo", "1D76DB", "Construcción de software"),
    ("tipo:diseño", "E99695", "Diseño de la solución (modelos, diagramas, UI)"),
    ("tipo:documentación", "5319E7", "Documento final, anexos, actas"),
    ("tipo:pruebas", "D93F0B", "Pruebas unitarias, integración, QA"),
    ("tipo:gestión", "C5DEF5", "Planificación, riesgos, comunicaciones, control"),
    # fase del EDT (mismos colores que el diagrama EDT)
    ("fase:0-gestión", "1F3B57", "Fase 0 · Gestión del proyecto (transversal)"),
    ("fase:1-análisis", "2E7D32", "Fase 1 · Análisis y especificación"),
    ("fase:2-diseño", "1565C0", "Fase 2 · Diseño de la solución"),
    ("fase:3-construcción", "E65100", "Fase 3 · Construcción del sistema"),
    ("fase:4-calidad", "6A1B9A", "Fase 4 · Aseguramiento de calidad"),
    ("fase:5-despliegue", "AD1457", "Fase 5 · Despliegue y transferencia"),
    ("fase:6-cierre", "00695C", "Fase 6 · Documentación y cierre"),
    # prioridad MoSCoW (a nivel de requisito, usada en las tarjetas de módulo)
    ("prioridad:debe", "B60205", "Requisito «Debe» (Must)"),
    ("prioridad:debería", "FBCA04", "Requisito «Debería» (Should)"),
    # módulos del dominio (M0–M9)
    ("módulo:M0", "5C4033", "M0 · Levantamiento de inventario inicial"),
    ("módulo:M1", "0E8A16", "M1 · Seguridad, maestros y auditoría"),
    ("módulo:M2", "1D76DB", "M2 · Recepción de producto"),
    ("módulo:M3", "5319E7", "M3 · Almacenamiento y ubicación"),
    ("módulo:M4", "B60205", "M4 · Transformación y balance de masa"),
    ("módulo:M5", "D93F0B", "M5 · Embultaje y alistamiento"),
    ("módulo:M6", "FBCA04", "M6 · Despacho mayorista y traslado a PDV"),
    ("módulo:M7", "0B8A8F", "M7 · Punto de venta"),
    ("módulo:M8", "C2E0C6", "M8 · Conteo físico y ajustes"),
    ("módulo:M9", "BFD4F2", "M9 · Trazabilidad, reportes e indicadores"),
]


def ensure_labels(owner, repo, dry_run):
    print("\n— Labels —")
    for name, color, desc in LABELS:
        if dry_run:
            print(f"  [dry-run] label: {name}")
            continue
        gh(
            "label", "create", name,
            "--repo", f"{owner}/{repo}",
            "--color", color,
            "--description", desc,
            "--force",
            check=False,
        )
        print(f"  ✓ {name}")


# ---------------------------------------------------------------------------
# 2. Milestones (hitos H1, E1, H2, E2, H3, EF)
# ---------------------------------------------------------------------------

MILESTONES = [
    ("H1 · Requisitos y diseño cerrados", "2026-08-30",
     "Semana 4. Backlog priorizado, requisitos (66 RF/10 RNF) y diseño cerrados."),
    ("E1 · Entrega 1 de la asignatura", "2026-09-13",
     "Semana 6. Primera entrega documental de Proyecto de Grado I."),
    ("H2 · Núcleo construido (M0–M3)", "2026-09-27",
     "Semana 8. Diseño cerrado; módulos M0 a M3 construidos y probados."),
    ("E2 · Entrega 2 de la asignatura", "2026-10-25",
     "Semana 12. Segunda entrega documental de Proyecto de Grado I."),
    ("H3 · Alcance comprometido construido y probado", "2026-11-08",
     "Semana 14. Los 10 módulos construidos y probados; medición postimplementación."),
    ("EF · Entrega final Proyecto de Grado I", "2026-11-11",
     "Semana 15. Documento completo, anexos y cierre de Proyecto de Grado I."),
]


def ensure_milestones(owner, repo, dry_run):
    print("\n— Milestones —")
    existing = {}
    if not dry_run:
        data = gh_json(
            "api", f"repos/{owner}/{repo}/milestones?state=all&per_page=100"
        ) or []
        if isinstance(data, list):
            existing = {m["title"]: m["number"] for m in data}

    for title, due, desc in MILESTONES:
        if dry_run:
            print(f"  [dry-run] milestone: {title} (vence {due})")
            continue
        if title in existing:
            print(f"  = ya existe: {title}")
            continue
        gh(
            "api", f"repos/{owner}/{repo}/milestones",
            "-f", f"title={title}",
            "-f", f"state=open",
            "-f", f"description={desc}",
            "-f", f"due_on={due}T00:00:00Z",
            check=False,
        )
        print(f"  ✓ {title}")


# ---------------------------------------------------------------------------
# 3. Borrar el tablero (Project v2) existente
# ---------------------------------------------------------------------------

def delete_existing_projects(owner, repo, auto_yes, dry_run):
    print("\n— Tablero existente —")
    if dry_run:
        print("  [dry-run] se listarían y (con confirmación) borrarían los "
              "tableros existentes del dueño indicado.")
        return

    projects = gh_json("project", "list", "--owner", owner, "--format", "json")
    items = (projects or {}).get("projects", [])
    if not items:
        print("  (no hay tableros existentes en esta cuenta)")
        return

    print("  Tableros encontrados:")
    for p in items:
        print(f"    #{p['number']} — {p['title']}  ({p['url']})")

    if not auto_yes:
        resp = input(
            "\n  ¿Borrar TODOS los tableros de arriba antes de crear el nuevo? [s/N]: "
        ).strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            print("  Cancelado el borrado; se conservan los tableros existentes.")
            return

    for p in items:
        gh("project", "delete", str(p["number"]), "--owner", owner, check=False)
        print(f"  ✓ borrado #{p['number']} — {p['title']}")


# ---------------------------------------------------------------------------
# 4. Crear el tablero nuevo + campo "Estado"
# ---------------------------------------------------------------------------

ESTADO_OPTIONS = ["Backlog", "En progreso", "En revisión", "Hecho", "Bloqueado"]


def create_project(owner, repo, dry_run):
    print("\n— Tablero nuevo —")
    if dry_run:
        print(f"  [dry-run] crear proyecto: {PROJECT_TITLE}")
        return None, None

    data = gh_json(
        "project", "create", "--owner", owner, "--title", PROJECT_TITLE,
        "--format", "json",
    )
    number, project_id = data["number"], data["id"]
    print(f"  ✓ creado #{number} — {data['url']}")

    gh("project", "link", str(number), "--owner", owner, "--repo",
       f"{owner}/{repo}", check=False)
    print(f"  ✓ vinculado al repositorio {owner}/{repo}")

    gh(
        "project", "field-create", str(number), "--owner", owner,
        "--name", "Estado", "--data-type", "SINGLE_SELECT",
        "--single-select-options", ",".join(ESTADO_OPTIONS),
        check=False,
    )
    print(f"  ✓ campo «Estado» creado: {', '.join(ESTADO_OPTIONS)}")

    return number, project_id


def get_estado_field(owner, number):
    fields = gh_json("project", "field-list", str(number), "--owner", owner,
                      "--format", "json")
    for f in (fields or {}).get("fields", []):
        if f.get("name") == "Estado":
            options = {o["name"]: o["id"] for o in f.get("options", [])}
            return f["id"], options
    return None, {}


# ---------------------------------------------------------------------------
# 5. Datos del EDT: todas las actividades del tablero
# ---------------------------------------------------------------------------

def issue(code, title, body_lines, labels, milestone=None):
    return {
        "code": code,
        "title": f"{code} · {title}",
        "body": "\n".join(body_lines),
        "labels": labels,
        "milestone": milestone,
    }


ISSUES = []

# --- Fase 0: Gestión del proyecto (transversal, semanas 1–16) --------------
FASE0 = "fase:0-gestión"
ISSUES += [
    issue("0.1", "Planificación", [
        "- [ ] Cronograma maestro y EDT",
        "- [ ] Backlog priorizado (MoSCoW)",
    ], [FASE0, "tipo:gestión"]),
    issue("0.2", "Ceremonias Scrum", [
        "- [ ] Planning, review y retrospectiva de cada sprint",
        "- [ ] Siete sprints de dos semanas calendarizados",
    ], [FASE0, "tipo:gestión"]),
    issue("0.3", "Riesgos", [
        "- [ ] Registro de incidencias (bitácora)",
        "- [ ] Escalera de descope con disparador definido",
    ], [FASE0, "tipo:gestión"]),
    issue("0.4", "Comunicaciones", [
        "- [ ] Actas con el director (quincenal)",
        "- [ ] Actas con el beneficiario (Pid Consulting S.A.S.)",
    ], [FASE0, "tipo:gestión"]),
    issue("0.5", "Control", [
        "- [ ] Repositorio, ramas y este mismo tablero de GitHub",
        "- [ ] Labels, milestones e issues por módulo y por documento base",
        "- [ ] Artefactos de control al día",
    ], [FASE0, "tipo:gestión"]),
]

# --- Fase 1: Análisis y especificación (semanas 1–4) ------------------------
FASE1 = "fase:1-análisis"
ISSUES += [
    issue("1.1", "Levantamiento de información", [
        "- [ ] Formato de 8 secciones diligenciado",
        "- [ ] Reglas de negocio y supuestos del negocio documentados",
        "- [ ] Mapa de 4 actores (Gerente, Jefe de bodega, "
        "Administrador de punto de venta, Consulta) y sus permisos",
    ], [FASE1, "tipo:gestión"], milestone="H1 · Requisitos y diseño cerrados"),
    issue("1.2", "Medición de línea base", [
        "- [ ] 12 pasos del proceso clasificados por tipo de soporte",
        "- [ ] Línea base de 10,2 min/movimiento · 92 % sin consolidar",
        "- [ ] 5 lotes analizados · 11 indicadores definidos",
    ], [FASE1, "tipo:gestión"], milestone="H1 · Requisitos y diseño cerrados"),
    issue("1.3", "Modelado del negocio", [
        "- [ ] BPMN AS-IS",
        "- [ ] BPMN TO-BE",
        "- [ ] Análisis con modelo BPSC",
    ], [FASE1, "tipo:diseño"], milestone="H1 · Requisitos y diseño cerrados"),
    issue("1.4", "Especificación de requisitos", [
        "- [ ] 66 RF en los 10 módulos (M0–M9), priorizados MoSCoW "
        "(64 «Debe», 2 «Debería»)",
        "- [ ] 10 RNF en 6 categorías de calidad (legal, rendimiento y "
        "consistencia, seguridad, trazabilidad y auditoría, usabilidad, "
        "compatibilidad)",
        "- [ ] 4 reglas de diseño (RD-01 a RD-04) que acotan el alcance",
    ], [FASE1, "tipo:documentación"], milestone="H1 · Requisitos y diseño cerrados"),
]

# --- Fase 2: Diseño de la solución (semanas 3–8) -----------------------------
FASE2 = "fase:2-diseño"
M2 = "H2 · Núcleo construido (M0–M3)"
ISSUES += [
    issue("2.1", "Modelo de datos", [
        "- [ ] Modelo entidad–relación, notación Chen clásica — 10 módulos "
        "M0–M9 (M9 como capa de reportes derivados, sin tablas propias)",
        "- [ ] Modelo físico PostgreSQL (DBML) — 41 tablas",
        "- [ ] Diccionario de datos completo",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.2", "Diagrama de contexto", [
        "- [ ] Sistema, actores y sistemas externos (Siigo)",
        "- [ ] Flujos de entrada y salida",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.3", "Diagrama de casos de uso", [
        "- [ ] 4 actores × 10 módulos",
        "- [ ] Trazabilidad contra los 66 RF",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.4", "Diagrama de clases", [
        "- [ ] Entidades del dominio y relaciones",
        "- [ ] Atributos, métodos y multiplicidad",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.5", "Diagramas de secuencia", [
        "- [ ] Recepción con generación de lote (M2)",
        "- [ ] Transformación y balance de masa (M4)",
        "- [ ] Despacho y descuento de existencias (M6)",
        "- [ ] Trazabilidad lote → punto de venta (M6–M7–M9)",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.6", "Arquitectura de software", [
        "- [ ] Diagrama de capas — presentación (Django + Bootstrap), "
        "lógica de negocio (apps M0–M9) y acceso a datos (ORM) sobre "
        "PostgreSQL",
        "- [ ] Diagrama de componentes — núcleo compartido M1, cadena "
        "operativa M0–M8 y capa de reportes M9, con Siigo como "
        "dependencia externa",
        "- [ ] Diagrama de despliegue — VPS único con Docker: contenedor "
        "web (Nginx + Gunicorn + Django) y contenedor db (PostgreSQL), "
        "HTTPS con Let's Encrypt, respaldo diario",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.7", "Seguridad y acceso", [
        "- [ ] Matriz RBAC de 4 perfiles × 10 módulos (RF-02)",
        "- [ ] Reglas de autorización de la gerencia (ajustes manuales, "
        "aprobación de inventario inicial)",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.8", "Diseño UI/UX", [
        "- [ ] Wireframes y prototipo en Figma",
        "- [ ] Validación con la gerencia",
    ], [FASE2, "tipo:diseño"], milestone=M2),
    issue("2.9", "Preparación del entorno", [
        "- [ ] Django + PostgreSQL corriendo en contenedores Docker "
        "(web y db)",
        "- [ ] Migraciones y datos de prueba",
        "- [ ] Repositorio, ramas y tablero listos",
    ], [FASE2, "tipo:desarrollo"], milestone=M2),
]

# --- Fase 3: Construcción del sistema — una tarjeta por módulo -------------
FASE3 = "fase:3-construcción"

MODULES = [
    ("M0", "Levantamiento de inventario inicial", "S3", "5–6", M2, [
        ("RF-62", "Levantamiento de inventario inicial", "debe"),
    ]),
    ("M1", "Seguridad, maestros y auditoría", "S3", "5–6", M2, [
        ("RF-01", "Autenticación de usuarios", "debe"),
        ("RF-02", "Control de acceso por perfil", "debe"),
        ("RF-03", "Usuario amarrado a un punto de venta", "debe"),
        ("RF-04", "Gestión de productos", "debe"),
        ("RF-05", "Gestión de ubicaciones de bodega", "debe"),
        ("RF-06", "Gestión de puntos de venta", "debe"),
        ("RF-07", "Gestión de clientes", "debe"),
        ("RF-08", "Gestión de tipos de embalaje", "debe"),
        ("RF-09", "Corrección de movimientos sin edición ni borrado", "debe"),
        ("RF-10", "Auditoría de operaciones", "debe"),
    ]),
    ("M2", "Recepción de producto", "S4", "7–8", M2, [
        ("RF-11", "Registro del documento del proveedor", "debe"),
        ("RF-12", "Registro de tandas de pesaje por lote", "debe"),
        ("RF-13", "Cálculo automático del peso neto", "debe"),
        ("RF-14", "Registro de temperatura por tanda", "debe"),
        ("RF-15", "Comparación de lo declarado contra lo recibido", "debe"),
        ("RF-16", "Evidencia fotográfica de recepción", "debe"),
        ("RF-17", "Cierre del documento del proveedor", "debe"),
    ]),
    ("M3", "Almacenamiento y ubicación", "S4", "7–8", M2, [
        ("RF-18", "Identificación única de cada lote", "debe"),
        ("RF-19", "Traslados internos entre zonas de bodega", "debe"),
        ("RF-20", "Existencia en tiempo real por lote y ubicación", "debe"),
        ("RF-21", "Registro único de todo movimiento de inventario", "debe"),
        ("RF-22", "Historial de movimientos de un lote", "debe"),
    ]),
    ("M4", "Transformación y balance de masa", "S5", "9–10",
     "E2 · Entrega 2 de la asignatura", [
        ("RF-23", "Registro de orden de transformación", "debe"),
        ("RF-24", "Generación de lotes derivados", "debe"),
        ("RF-25", "Cálculo automático de masa de salida y merma", "debe"),
        ("RF-26", "Cálculo del porcentaje de cierre", "debe"),
        ("RF-27", "Validación contra tolerancia configurable", "debe"),
        ("RF-28", "Trazabilidad hacia el lote de origen", "debe"),
        ("RF-29", "Confirmación como único punto de afectación de existencias", "debe"),
    ]),
    ("M5", "Embultaje y alistamiento", "S5", "9–10",
     "E2 · Entrega 2 de la asignatura", [
        ("RF-30", "Vencimiento heredado en cada bulto", "debe"),
        ("RF-31", "Rotulado de bultos", "debería"),
        ("RF-32", "Registro de pedidos de clientes mayoristas", "debe"),
        ("RF-33", "Sugerencia de lote por orden de entrada (FIFO)", "debe"),
        ("RF-34", "Alistamiento de pedidos", "debe"),
    ]),
    ("M6", "Despacho mayorista y traslado a punto de venta", "S6", "11–12",
     "E2 · Entrega 2 de la asignatura", [
        ("RF-35", "Documento de despacho mayorista", "debe"),
        ("RF-36", "Descuento inmediato en despacho mayorista", "debe"),
        ("RF-37", "Evidencia y firma del despacho mayorista", "debe"),
        ("RF-38", "Documento de traslado a punto de venta", "debe"),
        ("RF-39", "Envío visible para el punto de venta", "debe"),
        ("RF-40", "Registro de la cantidad despachada por línea", "debe"),
        ("RF-41", "Verificación de identidad de quien entrega", "debe"),
        ("RF-42", "Verificación de peso y aceptación del traslado", "debe"),
        ("RF-43", "Rechazo del traslado", "debe"),
        ("RF-44", "Corrección y reenvío tras un rechazo", "debe"),
        ("RF-45", "Reintentos hasta la aceptación", "debe"),
    ]),
    ("M7", "Punto de venta", "S6", "11–12",
     "E2 · Entrega 2 de la asignatura", [
        ("RF-46", "Registro de venta a consumidor final", "debe"),
        ("RF-47", "Registro de venta a restaurante por remisión", "debe"),
        ("RF-48", "Existencia en tiempo real por punto de venta", "debe"),
        ("RF-49", "Historial de movimientos de un punto de venta", "debe"),
    ]),
    ("M8", "Conteo físico y ajustes", "S7", "13–14",
     "H3 · Alcance comprometido construido y probado", [
        ("RF-50", "Registro de jornada de conteo físico", "debe"),
        ("RF-51", "Conteo aproximado por producto", "debe"),
        ("RF-52", "Consulta del conteo por gerencia", "debe"),
        ("RF-53", "Ajuste manual de existencia por gerencia", "debe"),
    ]),
    ("M9", "Trazabilidad, reportes e indicadores", "S7", "13–14",
     "H3 · Alcance comprometido construido y probado", [
        ("RF-54", "Trazabilidad de punta a punta de un lote", "debe"),
        ("RF-55", "Reporte consolidado de mermas", "debe"),
        ("RF-56", "Reporte de existencia por ubicación de bodega", "debe"),
        ("RF-57", "Reporte de existencia por punto de venta", "debe"),
        ("RF-58", "Alerta de vencimientos próximos", "debe"),
        ("RF-59", "Reporte de ventas y rotación por punto de venta", "debe"),
        ("RF-60", "Reporte de correcciones y ajustes", "debe"),
        ("RF-61", "Indicadores de gestión", "debería"),
        ("RF-63", "Consulta de inventario por múltiples criterios", "debe"),
        ("RF-64", "Informe general de inventario por periodo", "debe"),
        ("RF-65", "Alcance configurable de consultas e informes", "debe"),
        ("RF-66", "Exportación e impresión de informes en PDF y CSV", "debe"),
    ]),
]

for code, name, sprint, semanas, milestone, rfs in MODULES:
    body = [f"Sprint {sprint} · semanas {semanas}.", ""]
    for rf_id, rf_name, prio in rfs:
        mark = " «Debería»" if prio == "debería" else ""
        body.append(f"- [ ] **{rf_id}** — {rf_name}{mark}")
    labels = [FASE3, "tipo:desarrollo", f"módulo:{code}"]
    if any(p == "debería" for _, _, p in rfs):
        labels.append("prioridad:debería")
    if any(p == "debe" for _, _, p in rfs):
        labels.append("prioridad:debe")
    ISSUES.append(issue(
        code, f"Construcción — {name} ({len(rfs)} RF)", body, labels,
        milestone=milestone,
    ))

# --- Fase 4: Aseguramiento de calidad (continuo, S4–S7) --------------------
FASE4 = "fase:4-calidad"
H3 = "H3 · Alcance comprometido construido y probado"
ISSUES += [
    issue("4.1", "Pruebas unitarias", [
        "- [ ] Por sprint — balance de masa y saldos",
        "- [ ] Condición de la definición de terminado",
    ], [FASE4, "tipo:pruebas"], milestone=H3),
    issue("4.2", "Pruebas de integración", [
        "- [ ] Flujos de extremo a extremo",
        "- [ ] Trazabilidad lote → punto de venta",
    ], [FASE4, "tipo:pruebas"], milestone=H3),
    issue("4.3", "Verificación de los RNF", [
        "- [ ] Los 10 RNF verificados, en sus 6 categorías de calidad",
    ], [FASE4, "tipo:pruebas"], milestone=H3),
    issue("4.4", "Revisión cruzada de código", [
        "- [ ] Toda incorporación a la rama principal revisada por el "
        "otro integrante",
    ], [FASE4, "tipo:desarrollo"], milestone=H3),
    issue("4.5", "Medición postimplementación", [
        "- [ ] Contra los 11 indicadores de línea base",
    ], [FASE4, "tipo:pruebas"], milestone=H3),
]

# --- Fase 5: Despliegue y transferencia (semana 14) -------------------------
FASE5 = "fase:5-despliegue"
ISSUES += [
    issue("5.1", "Entorno de demostración", [
        "- [ ] Sistema desplegado en el VPS y accesible por URL "
        "(Nginx + Gunicorn + Django, HTTPS)",
        "- [ ] Listo para sustentación y beneficiario",
    ], [FASE5, "tipo:desarrollo"], milestone=H3),
    issue("5.2", "Carga de datos iniciales", [
        "- [ ] Catálogo real de productos",
        "- [ ] Existencias de arranque — M0 Levantamiento de inventario "
        "inicial",
    ], [FASE5, "tipo:desarrollo"], milestone=H3),
    issue("5.3", "Manual de usuario", [
        "- [ ] Guía de operación por perfil (Gerente, Jefe de bodega, "
        "Administrador de PDV, Consulta)",
    ], [FASE5, "tipo:documentación"], milestone=H3),
    issue("5.4", "Respaldo y recuperación", [
        "- [ ] Copia de la base de datos — pg_dump programado",
        "- [ ] Procedimiento de restauración probado",
    ], [FASE5, "tipo:desarrollo"], milestone=H3),
]

# --- Fase 6: Documentación y cierre (semanas 15–16) -------------------------
FASE6 = "fase:6-cierre"
EF = "EF · Entrega final Proyecto de Grado I"
ISSUES += [
    issue("6.1", "Documento final", [
        "- [ ] Capítulos 1 a 7 — estructura Universidad El Bosque",
    ], [FASE6, "tipo:documentación"], milestone=EF),
    issue("6.2", "Anexos del documento", [
        "- [ ] Anexo 1 BPMN AS-IS · Anexo 2 BPMN TO-BE",
        "- [ ] Anexo 3 diagramas UML — arquitectura, componentes y "
        "despliegue",
        "- [ ] Anexo 4 modelo de datos (Chen M0–M9, físico DBML, "
        "diccionario) y prototipo Figma",
    ], [FASE6, "tipo:documentación"], milestone=EF),
    issue("6.3", "Anexo de gestión del proyecto y del producto", [
        "- [ ] Artefactos de control y bitácoras",
        "- [ ] EDT, cronograma, presupuesto, riesgos y comunicaciones",
    ], [FASE6, "tipo:documentación"], milestone=EF),
    issue("6.4", "Verificación académica", [
        "- [ ] Compilatio",
        "- [ ] Declaración de uso de IA",
    ], [FASE6, "tipo:gestión"], milestone=EF),
    issue("6.5", "Sustentación", [
        "- [ ] Presentación y demostración del sistema",
    ], [FASE6, "tipo:gestión"], milestone=EF),
]

# --- Checkpoints de entrega documental (para que E1/E2 tengan tarjeta) ------
ISSUES += [
    issue("E1", "Preparar y enviar la Entrega 1 de la asignatura", [
        "- [ ] Consolidar los documentos de la Fase 1",
        "- [ ] Enviar en la plataforma académica antes de la fecha límite",
    ], ["fase:0-gestión", "tipo:gestión"],
        milestone="E1 · Entrega 1 de la asignatura"),
    issue("E2", "Preparar y enviar la Entrega 2 de la asignatura", [
        "- [ ] Consolidar avance de diseño y de los módulos construidos",
        "- [ ] Enviar en la plataforma académica antes de la fecha límite",
    ], ["fase:0-gestión", "tipo:gestión"],
        milestone="E2 · Entrega 2 de la asignatura"),
]


# ---------------------------------------------------------------------------
# 6. Crear los issues y agregarlos al tablero
# ---------------------------------------------------------------------------

def existing_issue_titles(owner, repo):
    data = gh_json(
        "issue", "list", "--repo", f"{owner}/{repo}",
        "--state", "all", "--limit", "500", "--json", "title,url",
    ) or []
    return {i["title"]: i["url"] for i in data}


def create_issues_and_add_to_board(owner, repo, project_number, dry_run):
    print(f"\n— Issues ({len(ISSUES)} en total) —")

    field_id, options = (None, {})
    if not dry_run:
        field_id, options = get_estado_field(owner, project_number)

    existing = {} if dry_run else existing_issue_titles(owner, repo)

    for it in ISSUES:
        if dry_run:
            print(f"  [dry-run] {it['title']}  labels={it['labels']}  "
                  f"milestone={it['milestone']}")
            continue

        if it["title"] in existing:
            url = existing[it["title"]]
            print(f"  = ya existe: {it['title']}")
        else:
            args = [
                "issue", "create", "--repo", f"{owner}/{repo}",
                "--title", it["title"], "--body", it["body"],
            ]
            for lb in it["labels"]:
                args += ["--label", lb]
            if it["milestone"]:
                args += ["--milestone", it["milestone"]]
            r = gh(*args, check=False)
            url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
            if not url:
                print(f"  ✗ no se pudo crear: {it['title']}")
                continue
            print(f"  ✓ {it['title']}")

        item = gh_json(
            "project", "item-add", str(project_number), "--owner", owner,
            "--url", url, "--format", "json",
        )
        item_id = (item or {}).get("id")

        if item_id and field_id and _project_node_id and "Backlog" in options:
            gh(
                "project", "item-edit",
                "--id", item_id,
                "--field-id", field_id,
                "--project-id", _project_node_id,
                "--single-select-option-id", options["Backlog"],
                check=False,
            )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner", help="Dueño del repo (usuario u org de GitHub)")
    ap.add_argument("--repo", help="Nombre del repositorio")
    ap.add_argument("--yes", action="store_true",
                     help="No preguntar antes de borrar tableros existentes")
    ap.add_argument("--dry-run", action="store_true",
                     help="Solo mostrar qué se haría, sin llamar a gh")
    args = ap.parse_args()

    if args.dry_run:
        owner = args.owner or "OWNER"
        repo = args.repo or "REPO"
    else:
        owner, repo = detect_owner_repo(args)
        preflight(owner, repo)

    ensure_labels(owner, repo, args.dry_run)
    ensure_milestones(owner, repo, args.dry_run)
    delete_existing_projects(owner, repo, args.yes, args.dry_run)
    project_number, project_id = create_project(owner, repo, args.dry_run)

    global _project_node_id
    _project_node_id = project_id

    if args.dry_run:
        print(f"\n— Issues ({len(ISSUES)} en total, dry-run) —")
        for it in ISSUES:
            print(f"  {it['title']}")
        print("\n[dry-run] Nada fue creado. Corre sin --dry-run para aplicar.")
        return

    create_issues_and_add_to_board(owner, repo, project_number, args.dry_run)

    print("\n" + "=" * 70)
    print("¡Listo! Tablero creado con "
          f"{len(LABELS)} labels, {len(MILESTONES)} milestones y "
          f"{len(ISSUES)} tarjetas.")
    print("\nÚltimo paso manual (10 segundos): abre el tablero en GitHub,")
    print("entra a la vista de tablero y cambia el agrupamiento (\"Group by\")")
    print("de \"Status\" a \"Estado\" para ver las columnas Backlog / En")
    print("progreso / En revisión / Hecho / Bloqueado que acabamos de crear.")
    print("=" * 70)


if __name__ == "__main__":
    main()
