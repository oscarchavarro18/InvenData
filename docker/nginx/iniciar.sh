#!/bin/sh
# Arranque de nginx: con certificado sirve HTTPS; sin él (la primera vez), solo HTTP
# para que Let's Encrypt valide el dominio. Recarga cada 6 horas para tomar las renovaciones.
set -e
if [ -f "/etc/letsencrypt/live/${DOMINIO}/fullchain.pem" ]; then
    modo=https
else
    modo=http
    echo "nginx: todavía no hay certificado para ${DOMINIO}; se sirve solo HTTP."
fi
envsubst '${DOMINIO}' < "/plantillas/${modo}.conf" > /etc/nginx/conf.d/default.conf
nginx -t
( while :; do sleep 6h; nginx -s reload; done ) &
exec nginx -g "daemon off;"
