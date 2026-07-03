FROM python:3.12-slim

# System libs for image processing (Pillow / OpenCV)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer stays cached across builds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ /app/app/

# Run as non-root
RUN useradd --create-home appuser
USER appuser

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]