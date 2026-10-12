#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare only a disposable Android debug trial; never build/install/run it.

Call after stage.py. The original Flutter dependency lock, web/iOS files and
shared integration overlay stay unchanged. This is not a release profile.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
STAGE_NAME = "overmorrow-hosted-android-ci"
PACKAGE = "org.volparossa.weather.trial"
ORIGIN = "http://127.0.0.1:43210"
TARGET = "lib/volparossa_native_trial.dart"
AGP = "8.11.1"
# Official Gradle all-distribution checksum; separate from the wrapper JAR.
GRADLE_SHA = "fba8464465835e74f7270bbf43d6d8a8d7709ab0a43ce1aa3323f73e9aa0c612"
GRADLE_URL = "file:///tools/android-inputs/gradle-8.13-all.zip"
MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <application android:label="VOLPAROSSA Weather Trial"
        android:icon="@mipmap/ic_launcher" android:allowBackup="false"
        android:usesCleartextTraffic="false"
        android:networkSecurityConfig="@xml/volparossa_loopback"
        android:enableOnBackInvokedCallback="true">
        <activity android:name="com.marotidev.overmorrow.MainActivity"
            android:exported="true" android:launchMode="singleTop"
            android:taskAffinity="" android:theme="@style/LaunchTheme"
            android:configChanges="orientation|keyboardHidden|keyboard|screenSize|smallestScreenSize|locale|layoutDirection|fontScale|screenLayout|density|uiMode"
            android:hardwareAccelerated="true" android:windowSoftInputMode="adjustResize">
            <meta-data android:name="io.flutter.embedding.android.NormalTheme" android:resource="@style/NormalTheme" />
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
        <meta-data android:name="flutterEmbedding" android:value="2" />
    </application>
</manifest>
'''
NETWORK = '''<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">127.0.0.1</domain>
    </domain-config>
</network-security-config>
'''
# Flutter f6ff1529's android_jar target/create_flutter_jar.py puts only native
# libraries in this separate artifact, not the Java embedding. AGP 8.11.1
# matches ignore expressions against the absolute input path. Do not generalize
# this to other engine versions, ABIs, embedding JARs or plugin dependencies.
ENGINE_VERSION = "1.0.0-1527ae0ec577a4ef50e65f6fefcfc1326707d9bf"
JETIFIER_NATIVE_JAR = (r"\A/state/gradle-home/caches/modules-2/files-2[.]1/io[.]flutter/x86_64_debug/"
    + ENGINE_VERSION.replace(".", "[.]") + r"/[0-9a-f]{40}/x86_64_debug-"
    + ENGINE_VERSION.replace(".", "[.]") + r"[.]jar\z")
# Properties.load removes one escaping level before Java Pattern sees \A/\z.
JETIFIER_NATIVE_PROPERTY = JETIFIER_NATIVE_JAR.replace("\\", "\\\\")
GRADLE_PROPERTIES = f'''org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:ReservedCodeCacheSize=128m -Dfile.encoding=UTF-8
org.gradle.workers.max=2
org.gradle.daemon=false
org.gradle.parallel=false
org.gradle.caching=false
kotlin.compiler.execution.strategy=in-process
android.useAndroidX=true
android.enableJetifier=true
android.jetifier.ignorelist={JETIFIER_NATIVE_PROPERTY}
android.experimental.lint.version=8.13.2
'''
REPLACED = ("android/app/build.gradle.kts", "android/settings.gradle.kts",
    "android/gradle/wrapper/gradle-wrapper.properties", "android/gradle.properties",
    "android/app/src/main/AndroidManifest.xml")
ADDED = ("android/app/src/main/res/xml/volparossa_loopback.xml", TARGET)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path, maximum=262144):
    require(path.resolve(strict=True) == path, "source path is not canonical")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
        and not info.st_mode & 0o022 and 0 < info.st_size <= maximum, "unsafe preparation input")
    return path.read_bytes()


def git(stage, *args):
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null",
        "-C", str(stage), *args], check=True, capture_output=True, timeout=20).stdout


def replace_once(raw, before, after):
    require(raw.count(before) == 1, "unexpected native upstream source")
    return raw.replace(before, after)


def planned(original, entrypoint):
    """Pure transformation, tested without Flutter/Gradle or filesystem writes."""
    result = dict(original)
    result[REPLACED[0]] = replace_once(original[REPLACED[0]],
        b'applicationId = "com.marotidev.Overmorrow"', f'applicationId = "{PACKAGE}"'.encode())
    result[REPLACED[1]] = replace_once(original[REPLACED[1]],
        b'id("com.android.application") version "8.9.1"', f'id("com.android.application") version "{AGP}"'.encode())
    wrapper = original[REPLACED[2]]
    require(b"distributionSha256Sum" not in wrapper and wrapper.count(b"gradle-8.13-all.zip") == 1,
        "unexpected Gradle distribution")
    wrapper = replace_once(wrapper, b"https\\://services.gradle.org/distributions/gradle-8.13-all.zip",
        GRADLE_URL.encode())
    result[REPLACED[2]] = wrapper.rstrip(b"\n") + f"\ndistributionSha256Sum={GRADLE_SHA}\n".encode()
    result[REPLACED[3]] = GRADLE_PROPERTIES.encode()
    result[REPLACED[4]] = MANIFEST.encode()
    result[ADDED[0]] = NETWORK.encode()
    result[TARGET] = entrypoint
    return result


def prepare(stage):
    stage = Path(stage).absolute()
    require(stage.resolve(strict=True) == stage and stage.parent == ROOT / "build"
        and stage.name == STAGE_NAME, "unexpected native stage")
    info = stage.stat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "stage must be private")
    pin = json.loads(regular(HERE / "upstream.json"))
    require(git(stage, "rev-parse", "HEAD").decode().strip() == pin["commit"], "upstream commit differs")
    lock = regular(stage / "pubspec.lock")
    require(sha(lock) == pin["pubspec_lock_sha256"], "upstream dependency lock differs")
    require(sha(regular(HERE / "upstream.patch")) == pin["upstream_patch_sha256"], "shared patch differs")
    original = {name: regular(stage / name) for name in REPLACED}
    for name, raw in original.items():
        require(raw == git(stage, "show", f'{pin["commit"]}:{name}'), "Android source already changed")
    activity = "android/app/src/main/kotlin/com/marotidev/overmorrow/MainActivity.kt"
    activity_source = regular(stage / activity)
    require(activity_source == git(stage, "show", f'{pin["commit"]}:{activity}')
        and b"package com.marotidev.overmorrow\n" in activity_source,
        "native activity package differs")
    for name in (*ADDED, "volparossa-native-profile.json"):
        target = stage / name
        require(not target.exists() and not target.is_symlink(), "native trial already prepared")
        require(target.parent.resolve(strict=True) == target.parent, "native target parent differs")
    entrypoint = regular(HERE / "native-android-entrypoint.dart")
    changes = planned(original, entrypoint)
    # Validate every target before changing the isolated stage, never a checkout.
    for name, raw in changes.items():
        target = stage / name
        if name in original:
            require(regular(target) == original[name], "native source changed during preparation")
        with target.open("wb" if name in original else "xb") as output:
            output.write(raw)
        target.chmod(0o600)
    require(regular(stage / "pubspec.lock") == lock, "dependency lock changed")
    receipt = dict(schema=1, kind="overmorrow-native-android-trial-profile",
        upstream_commit=pin["commit"], pubspec_lock_sha256=sha(lock), package=PACKAGE,
        target=TARGET, origin=ORIGIN, agp=AGP, gradle_version="8.13", gradle_sha256=GRADLE_SHA,
        gradle_distribution_url=GRADLE_URL, activity_sha256=sha(activity_source),
        source_before={name: sha(raw) for name, raw in original.items()},
        source_after={name: sha(raw) for name, raw in changes.items()},
        scope=dict(android_debug_trial=True, shared_overlay_changed=False, web_changed=False,
            ios_changed=False, dependency_lock_changed=False, production_authority=False,
            installed=False, native_execution=False, core_delivery=False))
    with (stage / "volparossa-native-profile.json").open("x") as output:
        json.dump(receipt, output, sort_keys=True, separators=(",", ":")); output.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(prepare(args.stage) if args.execute else dict(execute=False,
        package=PACKAGE, native_execution=False, production_authority=False), sort_keys=True))
