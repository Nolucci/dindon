FROM python:3.13-slim

WORKDIR /srv/dindon
COPY pyproject.toml ./
COPY app ./app
COPY db ./db
RUN pip install --no-cache-dir .

ENV DINDON_DB_DIR=/srv/dindon/db \
    DINDON_HOST=0.0.0.0

# The port is published on 127.0.0.1 only (see docker-compose.yml)
EXPOSE 8000
CMD ["dindon", "serve"]
