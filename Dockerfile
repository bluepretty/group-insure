# Group Insure — FastAPI backend
# Multi-stage build so the image stays small; the runtime only needs Python,
# not the full SDK.
FROM python:3.12-slim AS builder

WORKDIR /app

# Install the uv tool so we can resolve/compile dependencies without a shell
# that already has them.
RUN pip install --no-cache-dir uv

# Install project deps into the image's site-packages.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-project --no-dev

# Copy the whole project (app, tests, SQL files) and build the backend package.
COPY . .
RUN uv sync --no-dev --python 3.12

# Runtime image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/.venv/bin:$PATH"

WORKDIR /app

# Bring in the virtualenv built above (uv installs to /.venv by default).
COPY --from=builder /.venv /.venv
COPY --from=builder /app .

# App code lives under src/backend, where `app.main:app` resolves.
WORKDIR /app/src/backend

# Render passes PORT itself; fall back to 8000 locally.
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${PORT}/health').status==200 else 1)"

# gunicorn runs uvicorn workers so the process survives past the initial
# startup and binds the port Render exposes.
CMD ["sh", "-c", "gunicorn app.main:app --bind 0.0.0.0:${PORT} --workers 2 --worker-class uvicorn.workers.UvicornWorker --timeout 120"]
