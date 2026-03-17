FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Environment defaults (override in compose)
ENV PYTHONPATH=/app
ENV BUNDLES_DIR=/app/bundles
ENV OLLAMA_URL=http://host.docker.internal:18630
ENV QDRANT_URL=http://host.docker.internal:18650
ENV DEERFLOW_URL=http://deer-flow-gateway:2026
ENV OLLAMA_MODEL=nemotron-mini:4b
ENV USE_OLLAMA=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
