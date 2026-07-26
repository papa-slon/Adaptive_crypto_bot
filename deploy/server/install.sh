#!/usr/bin/env bash
# Install the delta-neutral carry bot alongside the bots already running on the
# Singapore host. Modelled on the turtle_bingx layout so the box stays uniform.
#
#   existing bot   -> /home/ubuntu/apps/bot/           port 8000   (untouched)
#   turtle bingx   -> /home/ubuntu/apps/turtle_bingx/  port 8080   (untouched)
#   THIS bot       -> /home/ubuntu/apps/carry_bot/     port 8090
#
# Safety posture: this script only ever ADDS. It never stops, restarts, edits or
# removes another service, never touches ports 8000/8080, and refuses to run if
# its own port is already taken. It installs the units but does NOT start them —
# starting is a separate, deliberate step after you have set the password.
#
#   bash install.sh              # install / update
#   bash install.sh --dry-run    # print what would happen, change nothing
set -euo pipefail

APP_NAME="carry_bot"
APP_DIR="/home/ubuntu/apps/${APP_NAME}"
REPO_URL="https://github.com/papa-slon/Adaptive_crypto_bot.git"
BRANCH="claude/crypto-algo-trading-bot-sti7oe"
PORT="${CARRY_PORT:-8090}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mXX\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [[ $DRY == 1 ]]; then printf '   [dry-run] %s\n' "$*"; else eval "$@"; fi; }

# ---------------------------------------------------------------- preflight
say "preflight"

[[ -d /home/ubuntu/apps ]] || die "/home/ubuntu/apps does not exist — is this the right host?"

# never collide with a service that is already listening
if ss -tln 2>/dev/null | grep -qE "[:.]${PORT}[[:space:]]"; then
    die "port ${PORT} is already in use. Re-run with CARRY_PORT=8091 bash install.sh"
fi
for reserved in 8000 8080; do
    if ss -tln 2>/dev/null | grep -qE "[:.]${reserved}[[:space:]]"; then
        say "  port ${reserved} in use (existing service) — leaving it alone"
    fi
done

command -v git >/dev/null || die "git is not installed"
PY=$(command -v python3.12 || command -v python3.11 || command -v python3) \
    || die "no python3 found"
say "  using $($PY --version)"
say "  target ${APP_DIR}, dashboard port ${PORT}"

# ---------------------------------------------------------------- code
if [[ -d "${APP_DIR}/.git" ]]; then
    say "updating existing checkout (no data is deleted)"
    run "git -C '${APP_DIR}' fetch --depth 1 origin '${BRANCH}'"
    run "git -C '${APP_DIR}' checkout -B '${BRANCH}' 'origin/${BRANCH}'"
elif [[ -e "${APP_DIR}" ]]; then
    die "${APP_DIR} exists but is not a git checkout — refusing to overwrite it."
else
    say "cloning ${BRANCH}"
    run "git clone --depth 1 --branch '${BRANCH}' '${REPO_URL}' '${APP_DIR}'"
fi

# ---------------------------------------------------------------- venv
say "python environment"
[[ -d "${APP_DIR}/.venv" ]] || run "$PY -m venv '${APP_DIR}/.venv'"
run "'${APP_DIR}/.venv/bin/pip' install --quiet --upgrade pip"
run "'${APP_DIR}/.venv/bin/pip' install --quiet pandas numpy cryptography"

say "running the bot's own test suite (offline, no orders)"
run "cd '${APP_DIR}' && '${APP_DIR}/.venv/bin/pip' install --quiet pytest && \
     '${APP_DIR}/.venv/bin/python' -m pytest algo_engine/tests -q"

# ---------------------------------------------------------------- config
if [[ ! -f "${APP_DIR}/.env" ]]; then
    say "creating .env (exchange keys are NOT stored here — they go in the web UI)"
    if [[ $DRY == 0 ]]; then
        PASS=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
        cat > "${APP_DIR}/.env" <<EOF
# Guards the /settings page AND derives the key that encrypts stored
# credentials. Generated once at install; change it and re-enter the keys.
BOT_ADMIN_PASSWORD=${PASS}
BOT_CONFIG_PATH=${APP_DIR}/logs/bot_config.enc
CARRY_VENUE=bingx-demo
CARRY_CAPITAL=200
CARRY_SLOTS=3
CARRY_LEVERAGE=1
CARRY_POLL=30
CARRY_RESCAN_MIN=60
EOF
        chmod 600 "${APP_DIR}/.env"
    fi
else
    say ".env already present — left untouched"
fi
run "mkdir -p '${APP_DIR}/logs'"

# ---------------------------------------------------------------- systemd
say "systemd units (installed, NOT started)"
for unit in carry-bot carry-dashboard; do
    src="${APP_DIR}/deploy/server/${unit}.service"
    [[ -f "$src" ]] || die "missing unit template ${src}"
    run "sudo install -m 644 '${src}' /etc/systemd/system/${unit}.service"
done
if [[ $DRY == 0 && "${PORT}" != "8090" ]]; then
    sudo sed -i "s/--port 8090/--port ${PORT}/" /etc/systemd/system/carry-dashboard.service
fi
run "sudo systemctl daemon-reload"
run "sudo systemctl enable carry-bot.service carry-dashboard.service"

# ---------------------------------------------------------------- done
cat <<EOF

$(say 'installed — nothing is running yet')

  1) start ONLY the dashboard first (read-only, places no orders):
       sudo systemctl start carry-dashboard.service
       systemctl status carry-dashboard --no-pager | head -5

  2) open it and enter the exchange keys in the browser:
       http://54.179.188.61:${PORT}/settings
       user: anything   password: the BOT_ADMIN_PASSWORD below
     (AWS security group must allow ${PORT}, or tunnel:
      ssh -L ${PORT}:127.0.0.1:${PORT} ubuntu@54.179.188.61 )

  3) only then start the bot itself:
       sudo systemctl start carry-bot.service
       journalctl -u carry-bot -f

  stop it again at any time:  sudo systemctl stop carry-bot

  password: $( [[ -f "${APP_DIR}/.env" ]] && grep '^BOT_ADMIN_PASSWORD=' "${APP_DIR}/.env" | cut -d= -f2- || echo '(dry-run)')

EOF
