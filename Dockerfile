# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS web
WORKDIR /build
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
COPY desktop/package.json desktop/package.json
RUN npm ci --workspace @cosecre/web --include-workspace-root --ignore-scripts --no-audit --no-fund
COPY frontend/ frontend/
RUN npm run build:web

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app/hub
COPY hub/pyproject.toml hub/uv.lock hub/README.md ./
COPY hub/src/ src/
RUN uv sync --locked --no-dev --compile-bytecode
# Compile the stdlib too: the runtime is read-only and cannot cache imports.
RUN python -m compileall -q /usr/local/lib/python3.12 /app/hub/src
COPY --from=web /build/frontend/dist /app/web
ENV COSECRE_STATIC_DIR=/app/web
EXPOSE 8000
CMD ["/app/hub/.venv/bin/python", "-m", "cosecre_hub.server"]
