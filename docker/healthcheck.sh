#!/usr/bin/env sh
# simple check: redis reachable & process list includes 'python'
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" PING | grep -q PONG || exit 1
pgrep -f "adaptive_crypto_bot.worker"   >/dev/null || exit 1
exit 0
