# Carry bot deploy image — runs the delta-neutral funding-carry bot on Bybit Demo.
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir pandas numpy

# only the engine is needed at runtime
COPY algo_engine /app/algo_engine

# logs are written here; mount a volume to keep them
RUN mkdir -p /app/logs
ENV PYTHONUNBUFFERED=1

# keys + sizing come from the environment (see .env.example) — never baked in.
# Default entrypoint is the AUTOPILOT: it scans funding and picks the coins
# itself. Override the entrypoint to run a single fixed symbol instead.
ENTRYPOINT ["python", "-m", "algo_engine.carry_bot.autopilot"]
