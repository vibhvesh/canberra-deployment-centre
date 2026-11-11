#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/vibhvesh/canberra-deployment-centre.git"
BASE="/opt/canberra"
SOURCE="$BASE/source"
APP="$BASE/deployment-console"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: curl -fsSL https://raw.githubusercontent.com/vibhvesh/canberra-deployment-centre/main/install.sh | sudo bash"
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer supports Ubuntu/Debian (apt-get) only."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip

mkdir -p "$BASE" "$APP" "$BASE/uploads" "$BASE/shared" "$BASE/projects" "$BASE/tools" "$BASE/audit"
if [[ -d "$SOURCE/.git" ]]; then
  git -C "$SOURCE" pull --ff-only
else
  rm -rf "$SOURCE"
  git clone --depth 1 "$REPO" "$SOURCE"
fi

install -d -m 700 /etc/canberra
if [[ ! -f /etc/canberra/console.env ]]; then
  PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  {
    printf 'CANBERRA_USERNAME=root\n'
    printf 'CANBERRA_PASSWORD=%s\n' "$PASS"
    printf 'CANBERRA_PORT=1101\n'
    printf 'CANBERRA_ROOT=/opt/canberra\n'
    printf 'CANBERRA_MAX_UPLOAD_MB=2048\n'
    printf 'CANBERRA_ALLOWED_IPS=\n'
  } > /etc/canberra/console.env
  chmod 600 /etc/canberra/console.env
  echo
  echo "SAVE THIS ROOT CONSOLE PASSWORD NOW:"
  echo "$PASS"
  echo
else
  echo "Existing /etc/canberra/console.env retained."
fi

install -d -m 700 "$APP/app"
cp -a "$SOURCE/app/." "$APP/app/"
install -m 644 "$SOURCE/requirements.txt" "$APP/requirements.txt"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --upgrade pip
"$APP/venv/bin/pip" install -r "$APP/requirements.txt"

cat > /etc/systemd/system/canberra-console.service <<EOF
[Unit]
Description=Canberra Deployment Centre
After=network.target
[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$APP
EnvironmentFile=/etc/canberra/console.env
ExecStart=$APP/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 1101
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now canberra-console
echo
echo "CDC installed. Open: http://SERVER_IP:1101"
echo "Status: systemctl status canberra-console"
echo "Logs: journalctl -u canberra-console -f"
echo "IMPORTANT: Restrict inbound TCP/1101 to your trusted IP in your server/cloud firewall."
