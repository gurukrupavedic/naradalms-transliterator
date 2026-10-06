# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
# Byte-compile at install so the first start doesn't, and the library's own import-time
# SyntaxWarnings never show up in the logs.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
WORKDIR /app

# ---- Install dependencies ----
# Only the manifests, so this layer is cached across code changes.
FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# ---- Runtime image ----
FROM deps AS runner
COPY src ./src
RUN uv sync --locked --no-dev \
    && useradd --system --no-create-home worker
USER worker

# A queue worker: it listens to nothing, it only needs REDIS_URL.
CMD ["/app/.venv/bin/transliterator"]
