# Atajos de trabajo (WSL/Linux). Uso: make up, make test, make lint ...
.PHONY: up down logs migrate makemigrations superusuario test lint format bash psql

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
