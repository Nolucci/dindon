# Stage 1: the interface (Svelte + Vite), built once. Nothing from the network is needed when the application runs.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Stage 2: the application (Python) and the built interface
FROM python:3.13-slim

# (No second runtime: the exporter is Python code of Dindon, export/)

WORKDIR /srv/dindon
COPY pyproject.toml ./
COPY app ./app
COPY db ./db
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
COPY --from=web /web/dist ./web/dist

# The application does not run as root: a user of its own, and an entrypoint that makes /data (inbox, archive) writable by it and then drops its privileges
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin dindon \
    && mkdir -p /data/inbox /data/archive && chown -R dindon:dindon /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV DINDON_DB_DIR=/srv/dindon/db \
    DINDON_WEB_DIR=/srv/dindon/web/dist \
    DINDON_INBOX=/data/inbox \
    DINDON_ARCHIVE=/data/archive \
    DINDON_HOST=0.0.0.0

# The port is published on 127.0.0.1 only (see docker-compose.yml)
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["dindon", "serve"]
