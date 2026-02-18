FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py .
COPY indexer/ indexer/
COPY backend/ backend/
COPY frontend/ frontend/
COPY data/categories.json data/categories.json

# Ensure all frontend subdirectories exist (even if empty in git)
RUN mkdir -p /app/frontend/assets

# Copy and prepare entrypoint
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create default data directory (will be overridden by volume mount)
RUN mkdir -p /data

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

# Use entrypoint script to ensure /data is writable before starting
ENTRYPOINT ["./entrypoint.sh"]
