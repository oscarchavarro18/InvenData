# InvenData — Sistema web de gestión y trazabilidad de inventarios

<!-- Insignias: reemplazar <ORG>/<REPO> por la ruta real del repositorio -->
<!-- ![CI](https://github.com/<ORG>/<REPO>/actions/workflows/ci.yml/badge.svg) -->

---

## 1. Descripción

InvenData es un sistema de información web para **Pid Consulting S.A.S.**, comercializadora de productos de río y mar en Neiva (Huila). La empresa registraba su inventario en papel, fotografías por WhatsApp y una hoja de cálculo: ningún paso del proceso quedaba en un sistema de inventario, el 92 % del tiempo de registro se consumía en esos soportes y la merma se aplicaba como un porcentaje fijo que se alejaba hasta cinco puntos porcentuales de la real en cada lote.

El sistema reemplaza esos soportes por un registro único por lote y ubicación. Registra la recepción por tandas de pesaje con descuento de tara, el movimiento entre cuartos fríos, la transformación con balance de masa, el despacho mayorista y el traslado a los puntos de venta con aceptación o rechazo, y genera reportes de existencias, mermas y trazabilidad. Lo usan la jefe de bodega, las administradoras de punto de venta y la gerencia, cada una con los permisos de su rol.

**Código Proyecto:** `<VERIFICAR: código asignado por el programa>`
**Periodo académico:** 2026-2 (Proyecto de Grado I) · cierre en 2027-1
**Programa:** Ingeniería de Sistemas · Universidad El Bosque · Modalidad Desarrollo Tecnológico
**Director:** Christian Felipe Duarte Arévalo

---

## 2. Integrantes

| Nombre completo | Usuario GitHub | Correo institucional | Rol en el equipo |
|---|---|---|---|
| Oscar Eduardo Chavarro Pedroza | [[@`<oscarchavarro18>`](https://github.com/oscarchavarro18)) | ochavarrop@unbosque.edu.co | Líder del proyecto · desarrollo full stack |
| Cristian David Gil | [@`<cgild2005>`](https://github.com/cgild2005) | cgild@unbosque.edu.co | Desarrollo full stack |

---

## 3. Tecnologías y requisitos previos

| Herramienta | Versión mínima | Notas |
|---|---|---|
| Docker Engine / Docker Desktop | 24.x | Ejecuta la aplicación y la base de datos en contenedores |
| Docker Compose | v2 | Incluido en Docker Desktop (`docker compose`) |
| Git | 2.40 | Control de versiones |
| GNU Make | 4.x | Atajos de desarrollo (`make migrate`, `make test`, …) |
| Python | `<VERIFICAR: versión de la imagen>` | Solo si se ejecuta fuera de Docker |
| Django | 5.2 | Framework web (incluido en la imagen) |
| PostgreSQL | 16 | Base de datos (contenedor `db`) |
| WSL 2 + Ubuntu | — | Solo en Windows, para usar `make` y Docker |

Componentes de la aplicación: plantillas de Django con CSS propio, Gunicorn y nginx en producción, pytest y ruff para pruebas y estilo, GitHub Actions para integración continua.

---

## 4. Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/<ORG>/<REPO>.git
cd <REPO>

# 2. Configurar variables de entorno
cp .env.example .env
# editar .env con los valores locales (base de datos, SECRET_KEY, DEBUG, ALLOWED_HOSTS)

# 3. Construir y levantar los contenedores
docker compose up -d --build

# 4. Crear las tablas y un usuario administrador
make migrate
make superusuario
```

> **Importante:** nunca subir el archivo `.env` ni credenciales reales al repositorio.
> `.env.example` contiene la lista de variables necesarias, sin valores.

En Windows, ejecutar los comandos desde la terminal de Ubuntu (WSL 2) con Docker Desktop abierto.

---

## 5. Cómo ejecutar el proyecto

### Desarrollo

```bash
docker compose up -d
```

- **URL local:** <http://localhost:8000>
- **Usuario de prueba:** se crea con `make superusuario`. El repositorio no publica credenciales.
- Para crear usuarios con los cuatro roles (jefe de bodega, administrador de punto de venta, gerente y consulta), ingresar con el superusuario al módulo de seguridad.

### Producción

El sistema está desplegado en un servidor privado virtual con Docker Compose: un contenedor con nginx, Gunicorn y Django y otro con PostgreSQL 16 con volumen persistente, certificado HTTPS (Let's Encrypt) y copia de seguridad diaria con `pg_dump`.

```bash
# en el servidor
docker compose -f <VERIFICAR: archivo compose de producción> up -d --build
```

---

## 6. Cómo ejecutar las pruebas

```bash
# Ejecutar toda la suite de pruebas
make test

# Ejecutar un archivo o un módulo
docker compose exec <VERIFICAR: servicio web> pytest <ruta/al/archivo_test.py>

# Revisión de estilo
docker compose exec <VERIFICAR: servicio web> ruff check .

# Reporte de cobertura
docker compose exec <VERIFICAR: servicio web> pytest --cov
```

- **Framework de pruebas:** pytest (con pytest-django) contra una base de datos PostgreSQL real.
- **Número de pruebas:** 997 `<VERIFICAR con la última ejecución de make test>`
- **Cobertura actual:** `<VERIFICAR: XX %>`
- **Qué se está probando:** servicios de negocio (recepción, movimientos, transformación con balance de masa, traslados, ventas, conteo y ajustes), vistas y permisos por rol y por ubicación. Cada función se prueba en el camino principal, en los permisos y en los errores de negocio.
- **Qué no se cubre todavía:** pruebas de aceptación con el personal de la organización (en curso) y pruebas de carga.

La integración continua (GitHub Actions) ejecuta ruff y pytest en cada pull request.

---

## 7. Estructura del repositorio

```text
<REPO>/
├── <VERIFICAR: carpeta del proyecto Django>/   # Configuración (settings, urls, wsgi)
├── <VERIFICAR: aplicaciones por módulo M0–M9>/ # Modelos, servicios, vistas, plantillas
├── tests/                                      # Pruebas automatizadas
├── .github/workflows/                          # Integración continua (ruff + pytest)
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

> Generar el árbol real con `tree -L 2 -I '__pycache__|.venv|node_modules'` y reemplazar este bloque.

---

## 8. Flujo de trabajo con Git

- Rama `main`: siempre estable, corresponde a lo desplegado. **No se hace push directo.**
- Rama `develop`: integración de los módulos.
- Ramas de trabajo: `feature/<modulo>-<descripcion-corta>`, `fix/<descripcion-corta>`, `docs/<descripcion-corta>`.
- Todo cambio entra a `develop` y luego a `main` mediante **Pull Request** revisado por el otro integrante y con la integración continua en verde.
- Mensajes de commit en formato [Conventional Commits](https://www.conventionalcommits.org/es/): `feat: agrega traslado con aceptación del punto de venta`, `fix: corrige cálculo de tara`.

---

## 9. Estado del proyecto y avances

| Entrega | Fecha | Alcance comprometido | Estado |
|---|---|---|---|
| H1 | 30/08/2026 | Línea base y requisitos cerrados | Completado |
| E1 | 13/09/2026 | Entrega 1 de la asignatura | Completado |
| H2 | 27/09/2026 | Diseño cerrado y entorno de desarrollo listo | Completado |
| E2 | 25/10/2026 | Primeros módulos funcionando | Completado |
| H3 | 08/11/2026 | Diez módulos (M0–M9) integrados | Completado |
| Despliegue | 16/11/2026 | Sistema publicado en el servidor y presentado a la organización | Completado |
| Pruebas y manual | Nov 2026 – 2027-1 | Pruebas con el personal y manual de usuario por rol | En curso |
| Entrega final | 2027-1 | Piloto, acta de aceptación y medición frente a la línea base | Pendiente |

Módulos implementados: inventario inicial (M0), seguridad, maestros y auditoría (M1), recepción por tandas (M2), almacenamiento por lote y ubicación (M3), transformación con balance de masa (M4), embultaje y alistamiento (M5), despacho mayorista y traslados (M6), ventas del punto de venta (M7), conteo físico y ajustes (M8), trazabilidad y reportes PDF/CSV (M9).

---

## 10. Decisiones técnicas relevantes

- **Monolito modular en capas** (vistas → servicios → ORM → PostgreSQL). Diez módulos dan orden sin la complejidad de servicios distribuidos, que no se justifica para un equipo de dos personas y cerca de mil movimientos al mes.
- **Servicios con transacciones atómicas.** Todo movimiento de existencias pasa por un único servicio dentro de `transaction.atomic`, junto con su registro de auditoría.
- **Libro de movimientos de solo anexado.** La existencia es una proyección calculada; un error se corrige con un movimiento inverso y nunca se edita ni se borra el original.
- **Dos libros de movimientos.** La bodega se controla por lote y ubicación; el punto de venta, por producto, porque allí la mercancía se mezcla en la vitrina.
- **Reglas de negocio también en la base de datos.** Llaves foráneas y restricciones de unicidad y verificación impiden, por ejemplo, existencias negativas o lotes duplicados aunque la aplicación falle.
- **Control de acceso por rol y por ubicación.** Cuatro roles que corresponden a cargos reales; el administrador de punto de venta solo opera su punto.
- **Siigo solo referenciado.** Siigo sigue siendo el sistema contable; InvenData guarda únicamente el número de factura.
- **Captura manual de peso y temperatura.** Sensores o RFID no se justifican a la escala de la organización; el problema medido era la consolidación del registro.
- **Docker Compose e integración continua.** El mismo entorno en desarrollo y producción, y ruff y pytest en cada pull request.

---

## 11. Limitaciones conocidas y trabajo futuro

- La temperatura se registra como un dato puntual en la recepción, sin monitoreo continuo.
- El registro en el lugar de la operación requiere conectividad en la bodega; está pendiente de confirmar en operación real.
- Las ventas del punto de venta se digitan en InvenData y en Siigo; no hay integración automática.
- Funciones aplazadas por la escalera de descope: rotulado de bultos e indicadores avanzados.
- Pendiente para 2027-1: operación en piloto, acta de aceptación y medición de las tres variables frente a la línea base (tiempo de registro, pasos con registro trazable y error de la merma por lote).
- Trabajo futuro: carga del archivo de ventas de Siigo, versión con registro sin conexión si las pruebas lo justifican y sensores de temperatura y peso cuando el registro consolidado sea estable.

---

## 12. Créditos y referencias

- Documentación de [Django 5.2](https://docs.djangoproject.com/en/5.2/) y de [PostgreSQL 16](https://www.postgresql.org/docs/16/).
- M. Fowler, *Patterns of Enterprise Application Architecture* (capa de servicios) y «Event Sourcing» (libro de movimientos).
- P. Olsen y M. Borit, componentes de un sistema de trazabilidad de alimentos; K. M. Karlsen, puntos críticos de trazabilidad.
- El análisis, los requisitos, las reglas de negocio y el modelo de datos se construyeron con la información de Pid Consulting S.A.S., con autorización de uso académico.

**Uso de asistentes de IA.** Se usaron como apoyo, con revisión del equipo:

- **GitHub Copilot:** autocompletado y sugerencias de código en partes de la lógica.
- **Claude (Anthropic) y Gemini (Google):** consultas puntuales sobre la lógica de algunas funciones, corrección de errores y configuración del entorno local.
- La arquitectura, el modelo de datos y las reglas de negocio los definió el equipo. Todo cambio entró por un pull request revisado por el otro integrante y pasó la revisión de estilo y las pruebas automatizadas de la integración continua.

El detalle completo está en la declaración de uso de IA del trabajo de grado.

---

## 13. Licencia

`<VERIFICAR: licencia acordada con la organización>` — ver el archivo [LICENSE](LICENSE).
