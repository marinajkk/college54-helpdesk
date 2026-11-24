#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${CODESPACE_NAME:?Открой терминал GitHub Codespaces}"
# Trust the MAX API issuer only in the bot processes.
cert_dir=$(mktemp -d)
trap 'rm -rf "$cert_dir"' EXIT
for kind in root sub; do
  curl --fail --silent --show-error --retry 2 --max-time 30 \
    "https://gu-st.ru/content/lending/russian_trusted_${kind}_ca_pem.crt" \
    -o "$cert_dir/$kind.crt"
  openssl x509 -in "$cert_dir/$kind.crt" -outform PEM -out "$cert_dir/$kind.pem"
done
cat "$cert_dir/root.pem" "$cert_dir/sub.pem" > "$cert_dir/max.pem"
python -m pip install -q -r requirements.txt
SSL_CERT_FILE="$cert_dir/max.pem" python - <<'PY'
import httpx
response = httpx.get("https://platform-api2.max.ru/me", timeout=20)
if response.status_code >= 500:
    raise SystemExit(f"MAX API: HTTP {response.status_code}")
PY
read -rsp "Вставь токен MAX и нажми Enter: " MAX_BOT_TOKEN
printf '\n'
[[ -n "$MAX_BOT_TOKEN" ]] || { echo "Получен пустой токен"; exit 1; }
export MAX_BOT_TOKEN
MAX_WEBHOOK_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')
export MAX_WEBHOOK_SECRET
SSL_CERT_FILE="$cert_dir/max.pem" python -m uvicorn max_bot:app --host 0.0.0.0 --port 8000 &
server=$!
trap 'kill "$server" 2>/dev/null || true; rm -rf "$cert_dir"' EXIT
for i in {1..30}; do
  kill -0 "$server" || exit 1
  if curl -fsS http://localhost:8000/ -o /dev/null 2>/dev/null; then break; fi
  sleep 1
done
curl -fsS http://localhost:8000/ -o /dev/null
gh codespace ports visibility 8000:public -c "$CODESPACE_NAME"
SSL_CERT_FILE="$cert_dir/max.pem" python max_bot.py "https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/max/webhook"
echo "Бот запущен. Открой MAX и отправь /start"
wait "$server"
