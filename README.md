# InvenData

Sistema web para la gestión y trazabilidad de inventarios de **Pid Consulting S.A.S.** (Neiva).
Proyecto de grado · Ingeniería de Sistemas · Universidad El Bosque.

**Stack:** Django 5.2 LTS · PostgreSQL 16 · Docker · Bootstrap 5 · pytest · ruff.

## Puesta en marcha (Windows 11 + WSL + Docker Desktop)

Requisitos: WSL con Ubuntu 24.04, Docker Desktop con la integración de WSL activada, Git,
GitHub CLI (`gh`) y VS Code con la extensión WSL.

> Clone el repositorio **dentro de WSL** (por ejemplo `~/proyectos/invendata`), no en `C:\`.
> Docker es mucho más rápido sobre el sistema de archivos de WSL.

```bash
git clone https://github.com/oscarchavarro18/InvenData.git ~/proyectos/invendata
cd ~/proyectos/invendata
make up              # crea .env si falta, construye y levanta web + db (aplica migraciones)
make superusuario    # crea el primer usuario (perfil Gerente)
```

Abra <http://localhost:8000/login/> (sistema), <http://localhost:8000/admin/> (administración)
y <http://localhost:8000/salud/> (verificación de salud).

## Comandos frecuentes

| Acción | Comando |
|---|---|
| Levantar / detener | `make up` / `make down` |
| Ver registro | `make logs` |
| Pruebas | `make test` |
| Crear migración | `make makemigrations app=maestros` |
| Aplicar migraciones | `make migrate` |
| Estilo | `make lint` / `make format` |
| Consola SQL | `make psql` |

La base de datos queda también en `localhost:5432` (usuario y clave en `.env`) para conectar
DBeaver o pgAdmin.

## Calidad

Antes de cada commit corren ganchos automáticos (estilo, espacios, claves privadas, archivos
grandes). Se activan una sola vez con `pipx install pre-commit` y `pre-commit install`.
Cada solicitud de incorporación corre además el CI de GitHub Actions: estilo, migraciones al
día y pruebas contra PostgreSQL.

## Más información

- Estructura del código y tablas por módulo: [docs/estructura.md](docs/estructura.md).
- Reglas de trabajo en Git: [docs/flujo-git.md](docs/flujo-git.md).
- Tablero de gestión: [docs/gestion-del-tablero.md](docs/gestion-del-tablero.md).

El código sigue el Diccionario de datos del proyecto: cada modelo usa `db_table` con el nombre
de la tabla del diccionario. Los datos iniciales reales los entrega Pid Consulting y se cargan
con el módulo M0; el repositorio no contiene datos de la empresa.
