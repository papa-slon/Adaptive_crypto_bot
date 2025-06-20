#!/usr/bin/env bash
set -e
echo "Waiting for Redis..."
while ! nc -z $REDIS_HOST $REDIS_PORT; do
  sleep 0.5
done
echo "Redis is up - starting bot"
exec "$@"