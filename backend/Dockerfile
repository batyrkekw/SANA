FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY dist ./dist
COPY src ./src
COPY scripts ./scripts
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
ARG INSTALL_AI=false
RUN if [ "$INSTALL_AI" = "true" ]; then uv sync --frozen --no-dev --extra ai; else uv sync --frozen --no-dev; fi
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY config /app/config
COPY --from=frontend /frontend/dist /app/dist
RUN useradd --uid 10001 --create-home sana && mkdir -p /data/assets /data/models && chown -R sana:sana /data /app
USER sana
ENV UV_CACHE_DIR=/home/sana/.cache/uv
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
