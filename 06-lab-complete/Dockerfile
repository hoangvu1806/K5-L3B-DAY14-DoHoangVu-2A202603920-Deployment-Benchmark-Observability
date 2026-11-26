# Stage 1: Builder — compile & install dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Runtime — minimal non-root production image
FROM python:3.11-slim AS runtime

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
