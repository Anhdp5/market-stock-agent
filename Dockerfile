# ZaloPay Stock Intelligence Agent — AgentBase Custom Agent runtime image
FROM python:3.11-slim

# System deps: lxml/pandas wheels are prebuilt, but keep build-essential + curl
# for any source builds and for the health probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    TZ=Asia/Ho_Chi_Minh

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure runtime-writable dirs exist (config also falls back to /tmp)
RUN mkdir -p /app/logs /app/data /app/reports

# AgentBase Runtime routes all traffic to port 8080
EXPOSE 8080

# Container health: the platform marks the runtime ACTIVE once /health returns 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "server.py"]
