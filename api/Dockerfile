# syntax=docker/dockerfile:1.7
# MakeMyEXE API (Render free web service, docs/DEPLOY.md). Build from the repo root:
#   docker build -f api/Dockerfile -t makemyexe-api .
#   docker run -p 8000:8000 -e DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db makemyexe-api
#
# Behind a TLS-inspecting proxy, pass its CA as an optional build secret:
#   docker build --secret id=ca_bundle,src=/path/to/ca.crt ...
ARG PYTHON_VERSION=3.12

# --- build: resolve from uv.lock, install the api package and spec, nothing else ---------------
FROM python:${PYTHON_VERSION}-slim AS build
# uv pinned, from PyPI (the build stage only; it is not in the final image).
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir --disable-pip-version-check uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# Workspace metadata first, so the dependency layer is reused until uv.lock changes.
COPY pyproject.toml uv.lock ./
COPY spec/pyproject.toml spec/pyproject.toml
COPY engine/pyproject.toml engine/pyproject.toml
COPY api/pyproject.toml api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --locked --no-dev --no-install-workspace --package makemyexe-api --extra postgres

# Our code: makemyexe-api (with its Alembic migrations) and makemyexe-spec, as real installs.
COPY spec/ spec/
COPY api/ api/
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --locked --no-dev --no-editable --package makemyexe-api --extra postgres

# --- runtime: the virtualenv, the catalog specs, a non-root user ---------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    CATALOG_DIR=/app/automations \
    PORT=8000
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin app
WORKDIR /app
# Owned by root and read-only for the app user.
COPY --from=build /app/.venv /app/.venv
COPY automations/ /app/automations/
USER app
EXPOSE 8000

# Render's pre-deploy command needs a paid plan, so migrations run here; they are a no-op when
# the schema is current. One worker: the free instance has 512 MB.
CMD ["sh", "-c", "python -m api.migrate && exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*' --no-server-header"]
