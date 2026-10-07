# Common tasks for the full-stack app (backend/ and web/). Run `make help` for the list.
# Node is picked up from .tools/node when it is installed there, otherwise from your PATH.
NODE_BIN := $(CURDIR)/.tools/node/bin
export PATH := $(NODE_BIN):$(PATH)
export NEXT_TELEMETRY_DISABLED := 1

.PHONY: help install api web build start test seed refresh snapshot warm

help:
	@echo "make install   install backend and web dependencies"
	@echo "make api       run the API on http://localhost:8000"
	@echo "make web       run the web app on http://localhost:3000 (needs the API running)"
	@echo "make build     production build of the web app; make start serves it"
	@echo "make test      backend and web tests"
	@echo "make refresh   pull new draws from the official sources now"
	@echo "make snapshot  rebuild backend/data/seed from the official sources"
	@echo "make warm      precompute model output for the last 100 draws of every game"

install:
	cd backend && uv sync --all-extras
	cd web && npm install

api:
	cd backend && uv run --all-extras uvicorn app.main:app --port 8000

web:
	cd web && npm run dev

build:
	cd web && npm run build

start:
	cd web && npm run start

test:
	cd backend && uv run --all-extras pytest
	cd web && npm run typecheck && npm run lint && npm test

seed refresh snapshot warm:
	cd backend && uv run --all-extras python -m app.cli $@
