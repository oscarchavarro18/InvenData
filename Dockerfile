# syntax=docker/dockerfile:1
# Una imagen con dos destinos: "dev" (desarrollo y pruebas) y "prod" (piloto en el VPS).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# ---------- Desarrollo: incluye pytest, ruff y pre-commit ----------
FROM base AS dev
COPY requirements/ requirements/
RUN pip install -r requirements/dev.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---------- Producción: solo lo necesario, con usuario sin privilegios ----------
FROM base AS prod
COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt
COPY . .
# La carpeta de fotos se crea aquí con su dueño: el volumen nuevo hereda esos permisos.
RUN useradd --create-home --uid 1000 invendata \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R invendata:invendata /app
USER invendata
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
# Los estáticos se juntan al construir: la imagen queda completa e igual en cualquier servidor.
RUN DJANGO_SECRET_KEY=solo-para-construir-la-imagen python manage.py collectstatic --noinput -v0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud/', timeout=4)"
CMD ["sh", "docker/entrypoint.prod.sh"]
