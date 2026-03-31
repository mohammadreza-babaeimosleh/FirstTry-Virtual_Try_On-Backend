# ─────────────────────────────────────────────────────────────────────────────
# backend_api_vertex_gcp — Google Cloud Run deployment
#
# Lightweight python:3.11-slim base (no GPU needed).
# Vertex AI handles inference; this service only orchestrates HTTP + GCS.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System libraries for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ /app/app/

# Cloud Run injects PORT automatically
ENV PORT=8080

CMD ["python", "-m", "app.main"]
