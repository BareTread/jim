FROM python:3.9-slim as builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.9-slim

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/browsers \
    CRAWL4AI_DB_PATH=/app/data \
    HOME=/app \
    PORT=11235

# Chrome flags for better container performance
ENV CHROME_FLAGS="--disable-gpu --disable-software-rasterizer --disable-dev-shm-usage --no-sandbox --disable-setuid-sandbox --disable-extensions --disable-audio-output --headless --disable-web-security --window-size=1920,1080 --remote-debugging-port=9222"

# Create app directory and data directories
WORKDIR /app
RUN mkdir -p /app/output /app/data && \
    mkdir -p /browsers && \
    chown -R nobody:nogroup /app /app/output /app/data /browsers && \
    chmod -R 755 /app /browsers

# Install and setup Playwright with minimal browser
RUN PLAYWRIGHT_BROWSERS_PATH=/browsers playwright install chromium && \
    chown -R nobody:nogroup /browsers

# Copy application code
COPY server.py .
COPY crawl_site.py .

# Switch to non-root user
USER nobody

# Expose the port
EXPOSE ${PORT:-11235}

# Health check with longer timeout and start period
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-11235}/health || exit 1

# Run the server with verbose logging
CMD echo "Starting server on port ${PORT:-11235}" && python -u server.py 
