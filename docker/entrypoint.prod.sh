#!/bin/sh
# Arranque del contenedor web en producción: aplica migraciones y levanta Gunicorn.
# Los estáticos ya vienen juntados en la imagen (ver Dockerfile).
set -e
python manage.py migrate --noinput
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --forwarded-allow-ips "*" \
    --access-logfile - \
    --error-logfile -
