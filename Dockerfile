# Stage 1: the interface (Svelte + Vite), built once. Nothing from the network is needed when the application runs.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Stage 2: the application (Python) and the built interface
FROM python:3.13-slim

# The exporter is a .NET program (mounted from exporter/bin): it needs the ICU libraries
RUN apt-get update \
 && apt-get install -y --no-install-recommends "$(apt-cache search --names-only '^libicu[0-9]+$' | cut -d' ' -f1 | sort | tail -1)" \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/dindon
COPY pyproject.toml ./
COPY app ./app
COPY db ./db
RUN pip install --no-cache-dir .
COPY --from=web /web/dist ./web/dist

ENV DINDON_DB_DIR=/srv/dindon/db \
    DINDON_WEB_DIR=/srv/dindon/web/dist \
    DINDON_INBOX=/data/inbox \
    DINDON_ARCHIVE=/data/archive \
    DINDON_HOST=0.0.0.0

# The port is published on 127.0.0.1 only (see docker-compose.yml)
EXPOSE 8000
CMD ["dindon", "serve"]
