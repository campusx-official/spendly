# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 1001 spendly \
 && useradd  --system --uid 1001 --gid spendly spendly

# Dependencies first — this layer caches until requirements change
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

# Application code, explicitly listed. No blanket `COPY . .` — belt and
# braces with .dockerignore so a stray spendly.db at the repo root can
# never land in a layer even if the ignore file is ever edited wrong.
COPY app.py ./
COPY database/ ./database/
COPY templates/ ./templates/
COPY static/ ./static/

# The DB lives on a volume, never in an image layer
ENV SPENDLY_DB_PATH=/data/spendly.db
RUN mkdir -p /data && chown spendly:spendly /data
VOLUME ["/data"]

USER spendly
EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/healthz', timeout=2)"]

CMD ["gunicorn", "--bind", "0.0.0.0:5001", \
     "--workers", "1", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "app:app"]
