# ── Stage 1: builder ─────────────────────────────────────────────────────

FROM python:3.11-slim AS builder

WORKDIR /app

# Upgrade packaging tools
RUN python -m pip install --upgrade \
    pip \
    setuptools \
    wheel

COPY requirements.txt .

# Prefer pre-built wheels instead of compiling packages
RUN pip install \
    --prefix=/install \
    --no-cache-dir \
    --timeout=300 \
    --only-binary=:all: \
    -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────

FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /install /usr/local

# Application source
COPY core.py ./core.py
COPY api.py ./api.py
COPY pipeline.py ./pipeline.py
COPY train_outage_model.py ./train_outage_model.py

# Data: artifacts and processed datasets
COPY data/artifacts/ ./data/artifacts/
COPY data/processed/ ./data/processed/
COPY data/steg-outage-data/data/processed/ ./data/steg-outage-data/data/processed/

# Writable directories
RUN mkdir -p \
    data/raw \
    data/steg-outage-data/data/raw

# Non-root user
RUN useradd --create-home --no-log-init appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=15s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]