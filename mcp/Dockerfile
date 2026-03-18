FROM python:3.11-slim

WORKDIR /app

# Install build tools and copy package files
COPY pyproject.toml .
COPY src/ src/
COPY __main__.py .

# Install the package and dependencies
RUN pip install --no-cache-dir .

# FastMCP transport settings (SSE for container deployment)
ENV FASTMCP_TRANSPORT=sse
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8090

# BundleFabric defaults (override in docker-compose)
ENV BF_API_URL=http://bundlefabric-api:8000
ENV BF_LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')" || exit 1

CMD ["bundlefabric-mcp"]
