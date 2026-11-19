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
mkdir -p "$vm/stage/bin" "$vm/stage/units" "$vm/medium"
manifest="$core/tests/helper/debian13-amd64-image-v1.json"
image="$vm/base.qcow2"
curl --fail --show-error --silent --location --connect-timeout 30 --max-time 600 --max-filesize 2147483648 \
    --max-redirs 3 --proto '=https' --proto-redir '=https' --output "$image" "$(jq -er '.url' "$manifest")"
digest=$(jq -er '.sha512 | select(test("^[a-f0-9]{128}$"))' "$manifest")
echo "$digest  $image" | sha512sum --check --strict -
guest_data=$vm/stage
git archive HEAD src scripts tests/native-cache/expiry.py tests/native-cache/android_channel.py tests/native-cache/read-client.mjs | tar -xf - -C "$guest_data"
# The app build stages this exact client next to the same Weather provider modules.
git show HEAD:integrations/drizzli/overlay/src/lib/services/volparossa/client.mjs > "$guest_data/src/drizzli-client.mjs"
install -m 0755 "$(realpath "$(command -v node)")" "$guest_data/bin/node"
ldd "$guest_data/bin/node" | tee "$vm/node.linkage"
if grep -qE 'not found|libnode\.so' "$vm/node.linkage"; then exit 1; fi
install -s -m 0755 "$core"/target/debug/{volparossa,volparossa-agent,volparossa-helper} \
    "$core/target/debug/examples/remember_weather_manifest" "$guest_data/bin/"
cp "$core"/packaging/systemd/{volparossa-helper.service,volparossa-agent.service,volparossa.sysusers,volparossa.tmpfiles} "$guest_data/units/"
mv -- "$artifacts/forecast.json" "$guest_data/forecast.json"
echo "$GITHUB_SHA" > "$guest_data/weather.sha"
echo "$CORE_SOURCE" > "$guest_data/core.sha"
# Archive the inputs without their private host staging directory. The guest
# installs this public code under a separately owned traversal boundary.
extra=()
device=()
if [[ "${1:-}" = --android ]]; then
    mv -- "$artifacts/air-quality.json" "$guest_data/air-quality.json"
    extra=(air-quality.json)
    test -f "$artifacts/mobile/booted"
    device=(-chardev "socket,id=mobile,path=$artifacts/mobile.sock,server=on,wait=off"
            -device virtserialport,chardev=mobile,name=weather.android)
fi
tar --create --file="$vm/medium/trial.tar" --directory="$guest_data" \
    bin units scripts src tests forecast.json weather.sha core.sha "${extra[@]}"
genisoimage -quiet -R -V WEATHERDATA -o "$vm/data.iso" "$vm/medium"
rm -rf --one-file-system -- "$guest_data" "$vm/medium"
echo 'instance-id: weather-expiry' > "$vm/meta"
cloud-localds "$vm/seed.img" tests/native-cache/guest.sh "$vm/meta"
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
