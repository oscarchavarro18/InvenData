#!/bin/sh
# Pide el primer certificado HTTPS a Let's Encrypt y reinicia nginx para que lo use.
# Requisitos: el dominio ya apunta a la IP del servidor y nginx está arriba en modo HTTP.
# Uso (en la carpeta del proyecto): sh docker/obtener-certificado.sh
set -eu
cd "$(dirname "$0")/.."
valor() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
DOMINIO="$(valor DOMINIO)"
CORREO_CERTIFICADOS="$(valor CORREO_CERTIFICADOS)"
[ -n "$DOMINIO" ] || { echo "Falta DOMINIO en .env"; exit 1; }
[ -n "$CORREO_CERTIFICADOS" ] || { echo "Falta CORREO_CERTIFICADOS en .env (avisos de vencimiento)"; exit 1; }
COMPOSE="docker compose -f docker-compose.prod.yml"
$COMPOSE run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMINIO" --email "$CORREO_CERTIFICADOS" \
    --agree-tos --no-eff-email --non-interactive
$COMPOSE restart nginx
echo "Certificado listo para $DOMINIO. Abra https://$DOMINIO"
