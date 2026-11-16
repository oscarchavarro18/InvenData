#!/bin/sh
# Copia de seguridad diaria de la base de datos y de las fotos, con verificación y rotación.
# Pensado para cron en el servidor, por ejemplo a las 2:30 a. m.:
#   30 2 * * * cd /opt/invendata && sh docker/respaldo.sh >> /var/log/invendata-respaldo.log 2>&1
set -eu
umask 077  # los respaldos contienen todos los datos: solo los lee el dueño
cd "$(dirname "$0")/.."
DESTINO="${DESTINO_RESPALDOS:-/var/backups/invendata}"
DIAS="${DIAS_RESPALDO:-14}"
FECHA="$(date +%Y%m%d-%H%M)"
COMPOSE="docker compose -f docker-compose.prod.yml"
mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

# Base de datos en formato propio de PostgreSQL (comprimido y restaurable por partes).
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DESTINO/base-$FECHA.dump"
# Fotos y evidencias.
$COMPOSE run --rm --no-deps -T --entrypoint tar web -czf - -C /app media > "$DESTINO/fotos-$FECHA.tar.gz"

# Un respaldo que no se puede leer no sirve: se comprueba antes de borrar los viejos.
test -s "$DESTINO/base-$FECHA.dump"
$COMPOSE exec -T db pg_restore --list < "$DESTINO/base-$FECHA.dump" > /dev/null
tar -tzf "$DESTINO/fotos-$FECHA.tar.gz" > /dev/null

find "$DESTINO" -name 'base-*.dump' -mtime +"$DIAS" -delete
find "$DESTINO" -name 'fotos-*.tar.gz' -mtime +"$DIAS" -delete
echo "$(date '+%F %T') respaldo correcto: base-$FECHA.dump y fotos-$FECHA.tar.gz"
