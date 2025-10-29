# Use a stable Debian base where OpenJDK 17 is available
FROM python:3.11-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential openjdk-17-jdk git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

COPY . /app

RUN chmod +x ./*.sh || true

# Optional: expose (Render ignores it but okay to keep)
EXPOSE 10000

# ❌ REMOVE THIS LINE
# ENV PORT 10000

# ✅ Correct start command (Render injects PORT env automatically)
CMD gunicorn -w 1 -b 0.0.0.0:$PORT app:app
