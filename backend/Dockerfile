# домщенков.рф API. Build from the REPOSITORY ROOT (the image needs src/data for the catalog and consent texts):
#   docker build -f backend/Dockerfile -t domshchenkov-api .
# Base image: Docker Hub by default; server-setup.sh points Docker to a mirror, DSH_PYTHON_IMAGE overrides it
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

RUN useradd --system --uid 10001 --home /app app \
 && mkdir -p /var/lib/domshchenkov && chown app /var/lib/domshchenkov   # erasure tombstones (a named volume)
WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ ./
COPY src/data/ /app/src/data/

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)" || exit 1

# No access log from uvicorn: the app logs method, path (no query) and status itself.
# The client IP comes from X-Real-IP set by nginx and is trusted only from DSH_TRUSTED_PROXIES (app/api/deps.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log", "--no-proxy-headers"]
