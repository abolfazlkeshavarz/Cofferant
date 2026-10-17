# Cofferant
#
# Run `make help` for the command list.
#
# Requires: docker (for deployment), python 3.12+ (for local development).
# Works from PowerShell, cmd, or Git Bash — see the shell block below.

# ------------------------------------------------------------------- shell
# The recipes are bash (pipes, grep, [[ ]], $(...)). On Windows, make defaults
# to cmd.exe and a bare `SHELL := /bin/bash` does not resolve, so point SHELL
# at Git Bash by absolute path. The 8.3 short path (PROGRA~1) is deliberate:
# GNU Make 3.81 (GnuWin32) mis-parses a SHELL containing spaces.
# This block must come before any $(shell ...) call, which also uses SHELL.

ifeq ($(OS),Windows_NT)
    GIT_BASH_CANDIDATES := \
        C:/PROGRA~1/Git/bin/bash.exe \
        C:/PROGRA~2/Git/bin/bash.exe \
        $(subst \,/,$(LOCALAPPDATA))/Programs/Git/bin/bash.exe

    GIT_BASH := $(firstword $(foreach b,$(GIT_BASH_CANDIDATES),$(wildcard $(b))))

    ifeq ($(GIT_BASH),)
        $(error Git Bash not found. Install Git for Windows, or run make from a \
            Git Bash prompt. Looked in: $(GIT_BASH_CANDIDATES))
    endif

    SHELL := $(GIT_BASH)
else
    SHELL := /bin/bash
endif

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- settings
# Every value can be overridden on the command line:  make run PORT=9000
# Production secrets live in .env (see `make env`); this file never reads them.

PORT     ?= 8000
WEB_PORT ?= 8081
VERSION  ?= latest

# Local Python: the project's virtualenv when it exists.
PY := $(firstword $(wildcard .venv/Scripts/python.exe .venv/bin/python) python)

# Docker Desktop on Windows does not put docker on PATH for the non-login shell
# make spawns. Resolve it here with $(wildcard) and export the result so the
# scripts do not have to repeat the search.
DOCKER ?= docker

ifeq ($(OS),Windows_NT)
    DOCKER_CHECK := $(shell docker version 2>/dev/null)
    ifeq ($(DOCKER_CHECK),)
        DOCKER_CANDIDATES := \
            C:/PROGRA~1/Docker/Docker/resources/bin/docker.exe \
            C:/PROGRA~2/Docker/Docker/resources/bin/docker.exe \
            $(subst \,/,$(LOCALAPPDATA))/Programs/Docker/Docker/resources/bin/docker.exe \
            $(subst \,/,$(LOCALAPPDATA))/Programs/DockerDesktop/resources/bin/docker.exe

        DOCKER := $(firstword $(foreach d,$(DOCKER_CANDIDATES),$(wildcard $(d))))
        ifeq ($(DOCKER),)
            DOCKER := docker
        endif
    endif
endif

COMPOSE = $(DOCKER) compose

# NOTE: deliberately not a bare `export` (it blanks real environment variables on Windows).
export DOCKER

# All admin-* targets go through scripts/admin.sh, which talks to the running
# production container if there is one, else the local development database.
# Force with PROD=1 / PROD=0.
ADMIN = PROD="$(PROD)" bash scripts/admin.sh

.PHONY: help env up up-prebuilt down restart logs ps clean update \
        images images-bundle load-images bootstrap ssl \
        install migrate run demo test check \
        backup restore shell \
        admin-user admin-password migrate-tenants \
        health deploy-check deploy-health

# -------------------------------------------------------------------- help
help: ## Show this help
	@echo ""
	@echo "Cofferant - available targets"
	@echo ""
	@# Colour only when stdout is a terminal, so piping the output stays clean.
	@if [ -t 1 ]; then C=$$'\033[36m'; R=$$'\033[0m'; else C=""; R=""; fi; \
	grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk -v c="$$C" -v r="$$R" 'BEGIN {FS = ":.*?## "}; {printf "  %s%-22s%s %s\n", c, $$1, r, $$2}'
	@echo ""
	@echo "Develop:   make install && make migrate && make demo && make run"
	@echo "Deploy:    make env && make up       (or on a fresh VPS: ./scripts/bootstrap-vps.sh)"
	@echo "  your SaaS domain:   MODE=platform   DOMAIN=cofferant.ir make env"
	@echo "  customer's domain:  MODE=standalone DOMAIN=menu.cafe.ir LICENSE_KEY=CFR-... LICENSE_SERVER_URL=https://cofferant.ir make env"
	@echo ""

# ------------------------------------------------------------ configuration
env: ## Create .env with freshly generated secrets (never overwrites). MODE=platform|standalone DOMAIN=...
	@bash scripts/init-env.sh

# ---------------------------------------------------- docker stack (prod-like)
up: ## Build and start the app
	@test -f .env || { echo "No .env yet. Run: make env"; exit 1; }
	$(COMPOSE) up -d --build
	@echo "Waiting for the app to become healthy..."
	@for i in $$(seq 1 90); do \
		st=$$($(COMPOSE) ps app --format '{{.Health}}' 2>/dev/null | head -1); \
		if [ "$$st" = "healthy" ]; then echo "App healthy."; exit 0; fi; \
		sleep 1; \
	done; \
	echo "App did not become healthy in 90s. Check: make logs"; exit 1

up-prebuilt: ## Start from the image loaded with make load-images, without building
	@test -f .env || { echo "No .env yet. Run: make env"; exit 1; }
	$(COMPOSE) up -d --no-build

down: ## Stop the app (data is kept)
	$(COMPOSE) down

restart: down up ## Restart the app

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100 app

ps: ## Container status
	$(COMPOSE) ps

clean: ## Stop the app AND delete its volumes (destroys all data)
	@read -r -p "This deletes every database and uploaded photo. Type 'yes' to continue: " a; \
	[ "$$a" = "yes" ] || { echo "Cancelled."; exit 1; }
	$(COMPOSE) down -v

update: ## Pull the latest code and rebuild (git pull + up)
	git pull --ff-only
	$(MAKE) up

images: ## Build the production image without starting anything
	$(DOCKER) build -t cofferant-app:$(VERSION) .

images-bundle: ## Build the image on THIS machine and pack it for a low-resource VPS
	@bash scripts/build-images.sh

load-images: ## Load an images-bundle tarball (run this ON the server). FILE=path optional
	@bash scripts/load-images.sh $(FILE)

bootstrap: ## One-shot setup on a fresh Ubuntu/Debian VPS. MODE= DOMAIN= LETSENCRYPT_EMAIL=
	@bash scripts/bootstrap-vps.sh

ssl: ## Configure host nginx + Let's Encrypt (platform: CHALLENGE=cloudflare|dns for the wildcard certificate)
	@bash scripts/deploy-host-nginx.sh

# ------------------------------------------------------------- development
install: ## Create .venv and install the requirements
	python -m venv .venv
	$(firstword $(wildcard .venv/Scripts/python.exe .venv/bin/python)) -m pip install -r requirements.txt

migrate: ## Apply database migrations locally
	$(PY) manage.py migrate

run: ## Run the development server on http://localhost:8000
	$(PY) manage.py runserver $(PORT)

demo: ## Load a demo menu, tables and sample orders (local, or PROD=1 on a demo server)
	@bash scripts/demo-data.sh

test: ## Run the test suite
	$(PY) manage.py test --noinput

check: ## Django system checks (+ deployment checks with DJANGO_DEBUG=0)
	$(PY) manage.py check

# ---------------------------------------------------------------- operations
shell: ## Open a Django shell (running container if any, else local)
	@$(ADMIN) shell

admin-user: ## Create another superuser interactively
	@$(ADMIN) createsuperuser

admin-password: ## Rotate the admin/developer password in .env and restart. [PASSWORD=...]
	@PASSWORD="$(PASSWORD)" bash scripts/rotate-admin-password.sh

migrate-tenants: ## Apply migrations to every hosted customer's database (the container does this on start)
	@$(ADMIN) migrate_tenants

backup: ## Timestamped backup of ALL data (databases, customers, photos) into backups/
	@mkdir -p backups
	@ts=$$(date +%Y%m%d-%H%M%S); \
	$(COMPOSE) exec -T app tar -C /app -czf - data media > backups/cofferant-$$ts.tar.gz; \
	echo "Wrote backups/cofferant-$$ts.tar.gz"

restore: ## Restore from FILE=backups/....tar.gz into the running app (replaces current data)
	@test -f "$(FILE)" || { echo "FILE is required: make restore FILE=backups/cofferant-....tar.gz"; exit 1; }
	@read -r -p "This REPLACES all current data with the backup. Type 'yes': " a; [ "$$a" = "yes" ] || { echo "Cancelled."; exit 1; }
	@$(COMPOSE) exec -T app tar -C /app -xzf - < "$(FILE)"
	@$(COMPOSE) restart app
	@echo "Restored from $(FILE)"

# ----------------------------------------------------------------- quality
health: ## Check the running stack
	@bash scripts/health.sh

deploy-check: ## Pre-flight checks before deploying (secrets, tests, repo hygiene)
	@bash scripts/deploy-check.sh

deploy-health: ## Check a deployed instance. HOST=https://your.domain
	@test -n "$(HOST)" || { echo "HOST is required: make deploy-health HOST=https://cofferant.ir"; exit 1; }
	@API_URL="$(HOST)" REMOTE=1 bash scripts/health.sh
