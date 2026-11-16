#!/bin/sh
# Restaura una copia de seguridad: la base de datos y, si se indica, las fotos.
# REEMPLAZA los datos actuales. Uso:
#   sh docker/restaurar.sh /var/backups/invendata/base-AAAAMMDD-HHMM.dump [/var/backups/invendata/fotos-AAAAMMDD-HHMM.tar.gz]
set -eu
cd "$(dirname "$0")/.."
BASE="${1:?Indique el archivo base-*.dump}"
FOTOS="${2:-}"
COMPOSE="docker compose -f docker-compose.prod.yml"
printf "Esto reemplaza la base de datos actual con %s. Escriba RESTAURAR para seguir: " "$BASE"
read -r respuesta
[ "$respuesta" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }

$COMPOSE stop web nginx
$COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$BASE"
if [ -n "$FOTOS" ]; then
    $COMPOSE run --rm --no-deps -T --entrypoint sh web -c 'rm -rf /app/media/* && tar -xzf - -C /app' < "$FOTOS"
fi
$COMPOSE up -d web nginx
echo "Restauración terminada. Revise que el sistema abra y que los datos sean los esperados."
