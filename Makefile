.PHONY: help up down logs test seed shell clean

help:
	@echo "EVE Diagnostic Booking Service — Developer Commands"
	@echo "---------------------------------------------------"
	@echo "make up        - Start PostgreSQL, Redis, and API via Docker Compose"
	@echo "make down      - Stop all containers and remove networks"
	@echo "make logs      - Follow container logs"
	@echo "make test      - Run Pytest test suite locally"
	@echo "make seed      - Populate sample centres, tests, and demo users"
	@echo "make shell     - Open bash shell inside running API container"
	@echo "make clean     - Remove python cache and temp files"

up:
	docker-compose up --build -d

down:
	docker-compose down -v

logs:
	docker-compose logs -f api

test:
	pytest -v --durations=10

seed:
	python -m scripts.seed

shell:
	docker-compose exec api /bin/sh

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
