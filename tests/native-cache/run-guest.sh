#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
# KVM only. The guest gets immutable inputs and a single bounded serial result.
set -euo pipefail
umask 077
test "$GITHUB_ACTIONS:$RUNNER_ENVIRONMENT" = true:github-hosted
test "$(id -u)" != 0
test -c /dev/kvm
repo=$(pwd -P)
test "$repo" = "$GITHUB_WORKSPACE"
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
core=$repo/build/core
test "$(git -C "$core" rev-parse HEAD)" = "$CORE_SOURCE"
case "${1:-}" in ''|--android) ;; *) exit 2 ;; esac
test "$#" -le 1
artifacts=$WEATHER_TRIAL
vm=$(mktemp -d "$artifacts/kvm.XXXXXX")
cleanup() { rm -rf --one-file-system -- "$vm"; }
trap cleanup EXIT
manifest="$core/tests/helper/debian13-amd64-image-v1.json"
image="$vm/base.qcow2"
curl --fail --show-error --silent --location --connect-timeout 30 --max-time 600 --max-filesize 2147483648 \
    --max-redirs 3 --proto '=https' --proto-redir '=https' --output "$image" "$(jq -er '.url' "$manifest")"
digest=$(jq -er '.sha512 | select(test("^[a-f0-9]{128}$"))' "$manifest")
echo "$digest  $image" | sha512sum --check --strict -
profile=desktop
device=()
if [[ "${1:-}" = --android ]]; then
    profile=android
    test -f "$artifacts/mobile/booted"
    device=(-chardev "socket,id=mobile,path=$artifacts/mobile.sock,server=on,wait=off"
            -device virtserialport,chardev=mobile,name=weather.android)
fi
bash tests/native-cache/pack-guest.sh "$profile" "$vm"
qemu-img create -q -f qcow2 -F qcow2 -b "$image" "$vm/overlay.qcow2" 8G
kvm_gid=$(stat -Lc %g /dev/kvm)
[[ "$kvm_gid" =~ ^[1-9][0-9]*$ ]]
test "$(getent group "$kvm_gid" | cut -d: -f1)" = kvm
sudo -n -- /usr/bin/setpriv --reuid "$(id -u)" --regid "$kvm_gid" --clear-groups \
    --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs --reset-env -- \
    timeout --kill-after=10s 420s qemu-system-x86_64 -accel kvm -cpu host -m 2048 -smp 2 -nic none \
    -display none -monitor none -serial "file:$vm/console" -no-reboot \
    -device virtio-serial-pci -chardev "file,id=result,path=$vm/result" -device virtserialport,chardev=result,name=weather.result \
    "${device[@]}" \
    -drive "if=virtio,format=qcow2,file=$vm/overlay.qcow2" -drive "if=virtio,readonly=on,format=raw,file=$vm/seed.img" \
    -drive "media=cdrom,readonly=on,format=raw,file=$vm/data.iso" || {
        grep -oE 'WEATHER_GUEST_LINE=[0-9]{1,5}|guest diagnostics \[.{0,240}\]' "$vm/console" | tail -5 || true
        exit 1
    }
test "$(stat -c%s "$vm/result")" -le 8192
if ! jq -e --arg app "$GITHUB_SHA" --arg engine "$CORE_SOURCE" \
    '.weather_sha == $app and .core_sha == $engine and .distinct_weather_owner and .core_refused_expired and
     .network_interfaces == ["lo"] and .http_after_expiry == 503 and .processes_joined and .private_directory_removed and
     .drizzli_rejected_expired and .drizzli_recovered and .revision_after_recovery == 2 and
     .manifest_id != .replacement_manifest_id' \
    "$vm/result" >/dev/null 2>&1; then
    grep -oE '^WEATHER_TRIAL_FAILED=[a-z-]{1,40}$' "$vm/result" || true
    grep -Eo 'guest diagnostics \[.{0,240}\]|File "[^"]*/expiry.py", line [0-9]{1,4}|WEATHER_GUEST_LINE=[0-9]{1,5}|WEATHER_API_DIAGNOSTIC=[A-Za-z0-9_,.=-]{1,180}|AssertionError:[ a-zA-Z]{1,100}' "$vm/console" | tail -12 || true
    exit 1
fi
echo "$digest  $image" | sha512sum --check --strict -
jq -c --arg image "$digest" '. + {kvm:true,guest_nics:0,guest_client_ingress_veth:true,debian13_image_sha512:$image,helper_and_agent_stopped:true}' "$vm/result" > "$artifacts/result.json"
