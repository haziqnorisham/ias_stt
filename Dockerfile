# --------------------------------------------------------------------------- #
# Stage 1 — build dependencies (uWSGI must be compiled)
# --------------------------------------------------------------------------- #
FROM python:3.11-slim AS builder

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends gcc build-essential python3-dev\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m venv /app/venv \
    && /app/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /app/venv/bin/pip install --no-cache-dir -r requirements.txt


# --------------------------------------------------------------------------- #
# Stage 2 — slim runtime
# --------------------------------------------------------------------------- #
FROM python:3.11-slim

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends curl gcc build-essential python3-dev\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtualenv (site-packages + uWSGI binary) from the builder.
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy application source.
COPY app/       ./app/
COPY run.py     ./

# Drop privileges.
RUN groupadd --system appuser \
    && useradd --system --no-create-home --gid appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

# uWSGI configuration (read at startup).
ENV FLASK_PORT=5000 \
    UWSGI_PROCESSES=2 \
    UWSGI_THREADS=2 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production
COPY uwsgi.ini ./uwsgi.ini

EXPOSE ${FLASK_PORT}

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -sf http://localhost:${FLASK_PORT}/api/health || exit 1

CMD uwsgi --ini uwsgi.ini \
    --master \ 
    --log-master \
    --http 0.0.0.0:${FLASK_PORT} \
    --processes ${UWSGI_PROCESSES} \
    --threads ${UWSGI_THREADS}
