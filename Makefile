# Atajos de trabajo (WSL/Linux). Uso: make up, make test, make lint ...
.PHONY: up down logs migrate makemigrations superusuario test lint format bash psql \
	prod-up prod-down prod-logs prod-ps prod-superusuario prod-respaldo prod-certificado

up:
	@test -f .env || cp .env.example .env
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f web
migrate:
	docker compose exec web python manage.py migrate
makemigrations:
	docker compose exec web python manage.py makemigrations $(app)
superusuario:
	docker compose exec web python manage.py createsuperuser
test:
	docker compose exec web pytest
lint:
	docker compose exec web ruff check . && docker compose exec web ruff format --check .
format:
	docker compose exec web ruff check --fix . && docker compose exec web ruff format .
bash:
	docker compose exec web sh
psql:
	docker compose exec db psql -U invendata -d invendata

# --- Producción (en el VPS; usan el .env de producción) ---
PROD = docker compose -f docker-compose.prod.yml
prod-up:
	$(PROD) up -d --build
prod-down:
	$(PROD) down
prod-logs:
	$(PROD) logs -f --tail=200 web nginx
prod-ps:
	$(PROD) ps
prod-superusuario:
	$(PROD) exec web python manage.py createsuperuser
prod-respaldo:
	sh docker/respaldo.sh
prod-certificado:
	sh docker/obtener-certificado.sh
