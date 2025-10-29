# Use a stable Debian base where OpenJDK 17 is available
FROM python:3.11-slim-bullseye

# Install system dependencies and OpenJDK (needed for pyjnius / Hedera SDK)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential openjdk-17-jdk git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for Docker layer caching)
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Copy the rest of the app code
COPY . /app

# Make shell scripts executable (if any)
RUN chmod +x ./*.sh || true

# Expose (optional) — Render auto-detects the actual runtime port
EXPOSE 10000

# ⚠️ Do NOT hardcode PORT here; Render assigns it dynamically
# ENV PORT 10000  ← REMOVE THIS LINE COMPLETELY ❌

# ✅ Start Gunicorn using Render-provided $PORT dynamically
CMD gunicorn -w 4 -b 0.0.0.0:$PORT app:app
