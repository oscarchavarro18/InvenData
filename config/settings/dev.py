"""Configuración de desarrollo (Docker en la máquina local)."""

from .base import *

DEBUG = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# En desarrollo no se exige el manifiesto de archivos estáticos comprimidos.
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
# En desarrollo, runserver sirve los estáticos; WhiteNoise solo se usa en producción.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]
