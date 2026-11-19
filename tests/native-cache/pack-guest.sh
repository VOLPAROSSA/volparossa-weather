#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
# Prepare read-only public inputs. Signing keys are generated only once the guest boots.
set -euo pipefail
umask 077
profile=$1
vm=$2
case "$profile" in desktop|android|iphone) ;; *) exit 2 ;; esac
test "$GITHUB_ACTIONS:$RUNNER_ENVIRONMENT" = true:github-hosted
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
core=$PWD/build/core
test "$(git -C "$core" rev-parse HEAD)" = "$CORE_SOURCE"
artifacts=$WEATHER_TRIAL
mkdir -p "$vm/stage/bin" "$vm/stage/units" "$vm/medium"
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
if [[ "$profile" != desktop ]]; then
    mv -- "$artifacts/air-quality.json" "$guest_data/air-quality.json"
    extra=(air-quality.json)
fi
if [[ "$profile" = iphone ]]; then
    mkdir "$guest_data/licenses"
    cp LICENSE "$guest_data/licenses/Weather"
    cp "$core/LICENSE" "$guest_data/licenses/Core"
    cp "$core/THIRD_PARTY_LICENSES.md" "$guest_data/licenses/Core-dependencies.md"
    node_version=$(node -p process.versions.node)
    [[ "$node_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
    # Hosted Ubuntu installs Node with n, which copies bin and share but omits
    # the distribution's root LICENSE. Obtain the notices for that exact release.
    curl --fail --silent --show-error --proto '=https' --max-time 60 --max-filesize 1048576 \
        "https://raw.githubusercontent.com/nodejs/node/v$node_version/LICENSE" -o "$guest_data/licenses/Node"
    test -s "$guest_data/licenses/Node"
    extra+=(licenses)
fi
tar --create --file="$vm/medium/trial.tar" --directory="$guest_data" \
    bin units scripts src tests forecast.json weather.sha core.sha "${extra[@]}"
genisoimage -quiet -R -V WEATHERDATA -o "$vm/data.iso" "$vm/medium"
rm -rf --one-file-system -- "$guest_data" "$vm/medium"
echo 'instance-id: weather-expiry' > "$vm/meta"
cloud-localds "$vm/seed.img" tests/native-cache/guest.sh "$vm/meta"
