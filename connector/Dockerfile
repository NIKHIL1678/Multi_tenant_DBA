# syntax=docker/dockerfile:1.7
# ZipZy DBA connector image: ghcr.io/zipzy/dba-connector
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY zipzy_connector ./zipzy_connector
RUN uv sync --locked --no-dev

FROM python:3.12-slim
# Fixed non-root user. /data (identity key) belongs to it so a fresh Docker volume is writable.
RUN useradd --create-home --uid 10001 connector \
 && mkdir -p /data /config \
 && chown connector:connector /data
WORKDIR /app
COPY --from=builder --chown=connector:connector /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    ZIPZY_CONFIG=/config/connector.yaml ZIPZY_DATA_DIR=/data
USER connector
VOLUME ["/data"]
ENTRYPOINT ["zipzy-connector"]
CMD ["run"]