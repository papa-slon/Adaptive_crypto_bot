#!/usr/bin/env bash
# very simple ping-pong health-probe
curl -sf http://localhost:8000/ping >/dev/null || exit 1
