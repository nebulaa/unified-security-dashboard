# syntax=docker/dockerfile:1.7
# Single backend image used by:
#   - Cloud Run service: API          (uvicorn app.api.main:app)
#   - Cloud Run service: normalizer   (uvicorn app.normalizer.main:app)
#   - Cloud Run job:     migrate      (python -m app.migrate upgrade head)
#   - Cloud Run job:     poller-*     (python -m app.pollers.<name>)
# The entrypoint is selected per Cloud Run resource via `--command`/`--args`.
#
# Build from repo root: docker build -f backend/Dockerfile .
#
# Runtime is Python 3.13 on Alpine. Dependencies ship musllinux wheels, so the
# build stage does not need a compiler.

FROM python:3.13-alpine AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM ghcr.io/astral-sh/uv:latest AS uv

# Build stage: install deps into a venv that we copy into the runtime stage.
FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Layer 1: dependencies only — this layer is cached as long as pyproject.toml
# is unchanged, even when application source files change.
COPY backend/pyproject.toml /app/pyproject.toml
RUN python -c 'import tomllib; from pathlib import Path; project = tomllib.loads(Path("/app/pyproject.toml").read_text()); print("\n".join(project["project"]["dependencies"]))' > /tmp/requirements.txt
RUN uv pip install -p /opt/venv/bin/python -r /tmp/requirements.txt

# Layer 2: application source — only triggers the fast project-only install
# step above, not the full dependency resolution.
COPY backend/app /app/app
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
RUN uv pip install -p /opt/venv/bin/python --no-deps -e /app

FROM base AS runtime
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
ENV PATH="/opt/venv/bin:$PATH"

RUN addgroup -S -g 1001 secdb \
    && adduser -S -u 1001 -G secdb -h /app secdb \
    && chown -R secdb:secdb /app
USER secdb

EXPOSE 8080
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
