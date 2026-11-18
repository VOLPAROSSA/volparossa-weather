#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
# Executed exclusively during NoCloud boot of the KVM guest with no network card.
set -euo pipefail
umask 077
root=/opt/weather-trial
status=/dev/virtio-ports/weather.result
stage=inputs
finish() {
    result=$?
    if ((result != 0)); then
        echo "WEATHER_TRIAL_FAILED=$stage" > "$status"
        journalctl -b -u volparossa-agent -u volparossa-helper --no-pager -o cat |
            python3 -c 'import re,sys; print("guest diagnostics",sorted(set(re.findall(r"\x22diagnostic_code\x22:\s*\x22([A-Z0-9_]{1,80})\x22",sys.stdin.read(65536)))))' > /dev/ttyS0 || true
    fi
    systemctl poweroff --no-block
}
trap finish EXIT
trap 'echo "WEATHER_GUEST_LINE=$LINENO" > /dev/ttyS0' ERR
test "$(id -u)" = 0
test "$(systemd-detect-virt --vm)" = kvm
test -c "$status"
test "$(ls /sys/class/net)" = lo
install -d -m 0755 "$root"
mount -o ro,nodev,nosuid,noexec /dev/disk/by-label/WEATHERDATA /mnt
tar --extract --file=/mnt/trial.tar --directory="$root" --no-same-owner
umount /mnt
cd "$root"
stage=install
install -m 0755 bin/node /usr/local/bin/node
install -m 0755 bin/volparossa bin/volparossa-agent /usr/bin
install -D -m 0755 bin/volparossa-helper /usr/libexec/volparossa/volparossa-helper
install -m 0644 units/*.service /etc/systemd/system/
systemd-sysusers "$root/units/volparossa.sysusers"
systemd-tmpfiles --create "$root/units/volparossa.tmpfiles"
useradd --system --user-group --no-create-home --groups volparossa-users --shell /usr/sbin/nologin weatherowner
cat > /etc/volparossa/config.yaml <<'CONFIG'
runtime_mode: development
roles:
  client: true
  relay: false
  exit: false
network:
  uplink: local_only
  listen_addresses: [/ip4/127.0.0.1/udp/0/quic-v1]
  bootstrap_peers: []
privacy:
  metrics_enabled: false
content_contribution:
  enabled: false
dns_cache:
  enabled: false
sharing:
  enabled: false
download_sharing:
  enabled: false
wifi_mesh:
  enabled: false
CONFIG
chown root:volparossa /etc/volparossa/config.yaml
chmod 0640 /etc/volparossa/config.yaml
stage=identity
state=/var/lib/volparossa
umask 077
head -c 32 /dev/urandom | base64 > "$state/trial-passphrase"
chown volparossa:volparossa "$state/trial-passphrase"
runuser -u volparossa -- volparossa init --identity "$state/identity.key" --passphrase-file "$state/trial-passphrase" >/dev/null
runuser -u volparossa -- volparossa config validate >/dev/null
install -d -m 0700 /etc/credstore.encrypted
systemd-creds encrypt --with-key=host --name=identity-passphrase "$state/trial-passphrase" /etc/credstore.encrypted/identity-passphrase
stage=helper
systemctl daemon-reload
systemctl start volparossa-helper
for i in {1..100}; do [[ -S /run/volparossa/helper.sock ]] && break; sleep .1; done
test -S /run/volparossa/helper.sock
systemctl is-active --quiet volparossa-helper
stage=agent
systemctl start volparossa-agent
for i in {1..200}; do [[ -S /run/volparossa/control/agent.sock ]] && break; sleep .1; done
test -S /run/volparossa/control/agent.sock
systemctl is-active --quiet volparossa-agent
stage=seed
install -d -o weatherowner -g weatherowner -m 0700 /run/weather-owner
chmod -R a+rX bin scripts src tests
chmod 0644 forecast.json
runuser -u volparossa -- volparossa content publish --input "$root/forecast.json" --cache "$state/forecast-cache" \
    --identity "$state/identity.key" --passphrase-file "$state/trial-passphrase" --manifest "$state/trial-manifest" \
    --name weather.public-community-cache-trial --revision 1 --content-type application/vnd.volparossa.forecast.v1+json \
    --lifetime-seconds 60 --quota-bytes 131072 --max-entries 16 --min-free-bytes 67108864 > /run/weather-owner/publication.json
key=$(python3 -c 'import json;print(json.load(open("/run/weather-owner/publication.json"))["publisher_key_hex"])')
runuser -u volparossa -- "$root/bin/remember_weather_manifest" "$state/forecast-cache" "$state/trial-manifest" "$key"
rm -- "$state/trial-passphrase" "$state/trial-manifest"
mv -- forecast.json /run/weather-owner/original.json
chown weatherowner:weatherowner /run/weather-owner/{original,publication}.json
chmod 0600 /run/weather-owner/{original,publication}.json
stage=owner
runuser -u weatherowner -- env GITHUB_SHA="$(cat weather.sha)" CORE_SOURCE="$(cat core.sha)" \
    python3 -B "$root/tests/native-cache/expiry.py" /run/weather-owner/original.json /run/weather-owner/publication.json > /run/result.json
stage=cleanup
test ! -e /run/weather-owner/original.json
rmdir /run/weather-owner
systemctl stop volparossa-agent volparossa-helper
test ! -S /run/volparossa/control/agent.sock
test ! -S /run/volparossa/helper.sock
test "$(systemctl show --property=MainPID --value volparossa-agent)" = 0
test "$(systemctl show --property=MainPID --value volparossa-helper)" = 0
test "$(stat -c%s /run/result.json)" -le 8192
cat /run/result.json > "$status"
