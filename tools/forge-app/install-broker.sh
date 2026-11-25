#!/bin/sh
# Install the token broker on soulglow. Run by the owner, with sudo:
#   sudo tools/forge-app/install-broker.sh <path-to-app-private-key.pem>
# Creates the forge-app system user, moves the key into its home (0400; the
# original file is removed), installs the minter and its timer, grants the
# agents' user (s) read on the spool by ACL, and mints once.
set -eu
KEY=${1:?usage: install-broker.sh <app-private-key.pem>}
APP_ID=${FORGE_APP_ID:-5839392}
ACCOUNTS=${FORGE_ACCOUNTS:-"Applesauce-Labs shermanhuman"}
READER=${FORGE_READER:-s}
HERE=$(cd "$(dirname "$0")" && pwd)

[ "$(id -u)" = 0 ] || { echo "install-broker.sh: run it with sudo" >&2; exit 2; }
command -v setfacl >/dev/null || { echo "install-broker.sh: setfacl not found (sys-apps/acl)" >&2; exit 2; }

id forge-app >/dev/null 2>&1 || useradd --system --home-dir /var/lib/forge-app --shell /sbin/nologin forge-app
install -d -m 0700 -o forge-app -g forge-app /var/lib/forge-app
install -m 0400 -o forge-app -g forge-app "$KEY" /var/lib/forge-app/app.pem
rm -f "$KEY"

install -d -m 0750 -o forge-app -g forge-app /var/spool/forge-app
setfacl -m "u:$READER:rx" /var/spool/forge-app

install -d -m 0755 /usr/local/lib/forge-app
install -m 0644 "$HERE/forge_mint.py" /usr/local/lib/forge-app/forge_mint.py
cat > /etc/forge-app.env <<ENV
FORGE_APP_ID=$APP_ID
FORGE_APP_KEY=/var/lib/forge-app/app.pem
FORGE_ACCOUNTS=$ACCOUNTS
FORGE_SPOOL=/var/spool/forge-app
FORGE_READER=$READER
ENV
chmod 0644 /etc/forge-app.env
install -m 0644 "$HERE/systemd/forge-app.service" "$HERE/systemd/forge-app.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now forge-app.timer
systemctl start forge-app.service
echo "install-broker.sh: done. Tokens:"; ls -l /var/spool/forge-app
