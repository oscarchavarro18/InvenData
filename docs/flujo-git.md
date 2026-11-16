# Flujo de trabajo en Git

## Ramas
- `main`: versión estable; solo recibe incorporaciones desde `develop` al cerrar un hito. Cada hito lleva una etiqueta (`v0.1-H1`, `v0.2-H2`…).
- `develop`: integración del trabajo de cada sprint.
- `feature/<RF>-<descripcion-corta>`: una rama por historia, creada desde `develop`. Ejemplo: `feature/RF-11-documento-proveedor`.

## Reglas
1. Nadie hace commit directo en `main` ni en `develop`: todo entra por solicitud de incorporación (Pull Request). GitHub no ofrece protección de ramas en repositorios privados del plan gratuito, así que la regla se hace cumplir con un gancho local (`no-commit-to-branch` de pre-commit) y con la revisión del equipo.
2. Toda solicitud la revisa el **otro integrante** antes de incorporarse.
3. La solicitud debe pasar el CI (estilo, migraciones al día, pruebas) y cumplir la lista de verificación de la plantilla.
4. Mensajes de commit en español, en imperativo y con el requisito: `RF-11: agrega registro del documento del proveedor`.
5. Una historia = un requisito (o un grupo pequeño) del tablero de GitHub Projects, etiquetada por módulo y sprint.

## Flujo de una historia
```bash
git checkout develop && git pull
git checkout -b feature/RF-11-documento-proveedor
# ... trabajar, make test, make lint ...
git add <archivos> && git commit -m "RF-11: agrega registro del documento del proveedor"
git push -u origin feature/RF-11-documento-proveedor
gh pr create --base develop
```

## Antes de cada commit
Active los ganchos una sola vez: `pipx install pre-commit && pre-commit install` (revisan estilo, espacios, claves privadas, archivos grandes y bloquean commits directos en `main` y `develop`).

## Definición de terminado de un módulo
Pruebas unitarias del módulo pasando, revisión cruzada, migraciones incluidas, y validación del prototipo con la gerencia antes de construir.
