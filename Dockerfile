FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a non-root user and a working directory.
RUN groupadd --system app && useradd --system --gid app --uid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Install system deps (curl for the smoke test; build-essential not needed for our wheels).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install \
        "fastapi==0.115.6" \
        "uvicorn[standard]==0.32.1" \
        "sqlmodel==0.0.22" \
        "alembic==1.14.0" \
        "psycopg[binary]==3.2.3" \
        "pydantic==2.10.3" \
        "pydantic-settings==2.6.1" \
        "jinja2==3.1.4" \
        "python-multipart==0.0.20" \
        "argon2-cffi==23.1.0" \
        "httpx==0.28.1" \
        "itsdangerous==2.2.0" \
    && pip install \
        "pytest==8.3.4" \
        "freezegun==1.5.1" \
        "hypothesis==6.128.2" \
        "ruff==0.8.3" \
        "anyio==4.7.0"

# Copy the application.
COPY . /app

# Ensure vendored HTMX is present (M1 commits it to repo; the COPY above includes it).

# Create a writable directory for SQLite if used.
RUN mkdir -p /app/data && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers"]
