FROM python:3.11-slim

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git && \
    rm -rf /var/lib/apt/lists/*

# python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# project
COPY . .

ENV PYTHONPATH=/app
CMD ["python", "-m", "adaptive_crypto_bot.run"]