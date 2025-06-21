# syntax=docker/dockerfile:1
FROM python:3.11-slim-bullseye

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# сначала только requirements.txt (чтобы слои кешировались)
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --only-binary=:all: --no-cache-dir "numpy<2.0" TA-Lib-Precompiled==0.4.25 && \
    pip install --no-cache-dir -r requirements.txt

# теперь всё остальное приложение
COPY . .
# healthcheck script
COPY docker/healthcheck.sh /docker/healthcheck.sh
RUN chmod +x /docker/healthcheck.sh

RUN pip install -e .

CMD ["python", "-m", "adaptive_crypto_bot.run"]
