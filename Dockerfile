FROM node:22.14.0-bookworm-slim AS web
WORKDIR /build/web
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM postgres:17.6-bookworm AS workflow_tools

FROM python:3.12.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libpq5 liblz4-1 libzstd1 && rm -rf /var/lib/apt/lists/*
COPY --from=workflow_tools /usr/lib/postgresql/17/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=workflow_tools /usr/lib/postgresql/17/bin/pg_restore /usr/local/bin/pg_restore
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --locked --extra models --no-dev
COPY knowledge ./knowledge
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=web /build/web/dist ./web/dist
ENV PATH="/app/.venv/bin:$PATH" WORKSPACE_ROOT=/workspace TEXT_PROVIDER=disabled VISION_ENABLED=false
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
