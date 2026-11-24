#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${CODESPACE_NAME:?Открой терминал GitHub Codespaces}"
read -rsp "Вставь токен MAX и нажми Enter: " MAX_BOT_TOKEN
printf '\n'
[[ -n "$MAX_BOT_TOKEN" ]] || { echo "Получен пустой токен"; exit 1; }
export MAX_BOT_TOKEN
python -m pip install -q -r requirements.txt
MAX_WEBHOOK_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')
export MAX_WEBHOOK_SECRET
python -m uvicorn max_bot:app --host 0.0.0.0 --port 8000 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
for i in {1..30}; do
  kill -0 "$server" || exit 1
  if curl -fsS http://localhost:8000/ -o /dev/null 2>/dev/null; then break; fi
  sleep 1
done
curl -fsS http://localhost:8000/ -o /dev/null
gh codespace ports visibility 8000:public -c "$CODESPACE_NAME"
python max_bot.py "https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/max/webhook"
echo "Бот запущен. Открой MAX и отправь /start"
wait "$server"
