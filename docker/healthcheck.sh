#!/usr/bin/env sh
# ── OK, если Redis отвечает и запущен python-процесс воркера ──
redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" PING | grep -q PONG || exit 1
pgrep -f "adaptive_crypto_bot.worker"  >/dev/null              || exit 1
exit 0
