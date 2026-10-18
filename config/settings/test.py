"""Configuración para pruebas automatizadas: rápida y sin efectos externos."""

from .base import *

DEBUG = False
SECRET_KEY = "clave-solo-para-pruebas"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]
