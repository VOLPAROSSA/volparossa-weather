#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
umask 077
test "$GITHUB_ACTIONS:$RUNNER_ENVIRONMENT" = true:github-hosted
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
work=$WEATHER_TRIAL/mobile
mkdir -m 0700 "$work"
group=$(stat -Lc %g /dev/kvm)
test "$(getent group "$group" | cut -d: -f1)" = kvm
node=$(realpath "$(command -v node)")
sudo -n /usr/bin/unshare --mount --net --pid --fork --kill-child=TERM --mount-proc -- \
    /bin/bash -ceu '
        ip link set lo up
        exec /usr/bin/setpriv --reuid "$1" --regid "$2" --clear-groups \
            --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs --reset-env -- \
            /usr/bin/python3 -B "$3" "$4" "$5" "$6" "$7"
    ' android-cache "$(id -u)" "$group" "$PWD/tests/native-cache/android_session.py" "$work" "$node" \
    "$(readlink /proc/self/ns/net)" "$GITHUB_SHA" &
session=$!
cleanup() {
    if kill -0 "$session" 2>/dev/null; then
        kill -TERM "$session" || true
        wait "$session" || true
    fi
    rm -rf --one-file-system -- "$work"
}
trap cleanup EXIT
for attempt in {1..300}; do
    [[ -f "$work/booted" ]] && break
    kill -0 "$session" || { wait "$session"; exit 1; }
    sleep 1
done
test -f "$work/booted"
bash tests/native-cache/run-guest.sh --android
wait "$session"
python3 -B - "$WEATHER_TRIAL" <<'CHECK'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
core = json.loads((root / 'result.json').read_text())
mobile = json.loads((root / 'installed.json').read_text())
ui = mobile['observations']
assert core['android_requests'] == {'initial': [200, 200], 'refused': [503, 200], 'recovered': [200, 200]}
assert mobile['weather_source'] == core['weather_sha'] and core['guest_nics'] == 0 and core['core_refused_expired']
assert ui['initial']['weather_manifest'] == core['manifest_id']
assert ui['recovered']['weather_manifest'] == core['replacement_manifest_id']
assert ui['initial']['weather_table'][0][0] == core['valid_at']
assert abs(float(ui['recovered']['weather_table'][0][1]) - core['temperature_c']) < 0.00001
CHECK
