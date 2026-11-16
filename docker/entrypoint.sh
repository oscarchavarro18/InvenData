#!/bin/sh
# Arranque del contenedor web en desarrollo: aplica migraciones y levanta el servidor.
set -e
python manage.py migrate --noinput
exec python manage.py runserver 0.0.0.0:8000
