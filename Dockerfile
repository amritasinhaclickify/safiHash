# Use a stable Debian base where OpenJDK 17 is available
FROM python:3.11-slim-bullseye

# install system deps and OpenJDK (for pyjnius)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential openjdk-17-jdk git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# set workdir
WORKDIR /app


# copy requirements first for layer caching
COPY requirements.txt /app/requirements.txt

# upgrade pip and install python deps (will build pyjnius here)
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# copy rest of the app
COPY . /app

# make sure any scripts are executable
RUN chmod +x ./*.sh || true

# expose port
EXPOSE 10000
# Render sets PORT env; gunicorn default bind should use $PORT
ENV PORT 10000

# start command
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]


