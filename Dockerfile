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
RUN useradd --create-home --uid 1000 invendata \
    && mkdir -p /app/staticfiles \
    && chown -R invendata:invendata /app
USER invendata
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
