#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Export a bounded source recipe, never a runtime or a consumer admission.

Only the fixed profiles below are read. The CLI root is this script's checkout;
output must be a new direct child of its existing build/. Git and byte checks
run again before the success manifest. External sources remain references.

Execution requires a private checkout/output on its own runner, with no
concurrent writer using the same UID. These guards do not provide general
protection against a malicious process running as the same user.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).absolute().parents[1]
HELPER = "scripts/prepare_hosted_source_recipe.py"
SCHEMA = 1
MAX_FILES = 128
MAX_FILE = 512 * 1024
MAX_TOTAL = 4 * 1024 * 1024
MAX_MANIFEST = 256 * 1024
BROWSER_COMMIT = "08bac388a0abfd06426bebe8f6fabd0157d2e709"
# Explicit reviewed source sets, not a caller-controlled or recursive selection.
PROFILES = {
    "drizzli": (
        ".github/workflows/hosted-clients.yml",
        "LICENSE",
        "integrations/drizzli/browser-fixture.mjs",
        "integrations/drizzli/build-plugins.json",
        "integrations/drizzli/overlay/src/lib/services/volparossa-mode.ts",
        "integrations/drizzli/overlay/src/lib/services/volparossa/client.d.mts",
        "integrations/drizzli/overlay/src/lib/services/volparossa/client.mjs",
        "integrations/drizzli/overlay/src/routes/weather/week/VolparossaAirQuality.svelte",
        "integrations/drizzli/overlay/src/routes/weather/week/VolparossaForecast.svelte",
        "integrations/drizzli/overlay/src/routes/weather/week/VolparossaWeek.svelte",
        "integrations/drizzli/prepare_build.py",
        "integrations/drizzli/smoke_browser.py",
        "integrations/drizzli/stage.py",
        "integrations/drizzli/test-client.mjs",
        "integrations/drizzli/test-render.mjs",
        "integrations/drizzli/upstream.json",
        "integrations/drizzli/upstream.patch",
        "scripts/build_eccodes.py",
        "scripts/hosted-clients-bwrap.apparmor",
        "scripts/hosted-decoder-bwrap.apparmor",
        "scripts/prepare_hosted_clients_ci.py",
        "scripts/prepare_hosted_decoder.py",
        "scripts/prepare_hosted_decoder_environment.py",
        "scripts/prepare_hosted_decoder_ci.py",
        "scripts/prepare_hosted_runtime.py",
        "scripts/serve-provider.mjs",
        "src/air-quality-core.mjs",
        "src/air-quality-provider.mjs",
        "src/air-quality.mjs",
        "src/core-cache.mjs",
        "src/ecmwf.mjs",
        "src/forecast.mjs",
        "src/noaa-gefs.mjs",
        "src/provider-core.mjs",
        "src/provider-http.mjs",
        "src/provider.mjs",
        "tests/air-quality-fixtures.mjs",
        "tests/fixtures.mjs",
        "tests/precipitation-fixtures.mjs",
        "third_party/apparmor-ci/LICENSE",
        "third_party/apparmor-ci/clients-provenance.json",
        "third_party/apparmor-ci/provenance.json",
        "third_party/eccodes-sources.json",
        "third_party/hosted-runtime-inputs.json",
        "third_party/hosted-runtime-npm.json",
        HELPER,
    ),
    "overmorrow": (
        ".github/workflows/hosted-overmorrow.yml",
        "LICENSE",
        "integrations/drizzli/browser-fixture.mjs",
        "integrations/drizzli/smoke_browser.py",
        "integrations/overmorrow/browser-fixture.mjs",
        "integrations/overmorrow/build.py",
        "integrations/overmorrow/deploy.py",
        "integrations/overmorrow/overlay/lib/api_key.dart",
        "integrations/overmorrow/overlay/lib/volparossa/products.dart",
        "integrations/overmorrow/overlay/lib/volparossa/profile.dart",
        "integrations/overmorrow/overlay/lib/volparossa/provider.dart",
        "integrations/overmorrow/overlay/lib/volparossa/views.dart",
        "integrations/overmorrow/overlay/test/volparossa_products_test.dart",
        "integrations/overmorrow/overlay/test/volparossa_provider_test.dart",
        "integrations/overmorrow/overlay/test/volparossa_ui_test.dart",
        "integrations/overmorrow/overlay/web/flutter_bootstrap.js",
        "integrations/overmorrow/smoke_browser.py",
        "integrations/overmorrow/smoke_core_browser.py",
        "integrations/overmorrow/smoke_table_browser.py",
        "integrations/overmorrow/stage.py",
        "integrations/overmorrow/table-fixture.mjs",
        "integrations/overmorrow/test-fixtures.mjs",
        "integrations/overmorrow/upstream.json",
        "integrations/overmorrow/upstream.patch",
        "scripts/build_eccodes.py",
        "scripts/hosted-clients-bwrap.apparmor",
        "scripts/hosted-decoder-bwrap.apparmor",
        "scripts/prepare_hosted_clients_ci.py",
        "scripts/prepare_hosted_decoder.py",
        "scripts/prepare_hosted_decoder_environment.py",
        "scripts/prepare_hosted_decoder_ci.py",
        "scripts/prepare_hosted_flutter.py",
        "scripts/prepare_hosted_overmorrow_ci.py",
        "scripts/prepare_hosted_runtime.py",
        "scripts/serve-provider.mjs",
        "src/air-quality-core.mjs",
        "src/air-quality-provider.mjs",
        "src/air-quality.mjs",
        "src/core-cache.mjs",
        "src/ecmwf.mjs",
        "src/forecast.mjs",
        "src/noaa-gefs.mjs",
        "src/provider-core.mjs",
        "src/provider-http.mjs",
        "src/provider.mjs",
        "tests/air-quality-fixtures.mjs",
        "tests/fixtures.mjs",
        "tests/precipitation-fixtures.mjs",
        "third_party/apparmor-ci/LICENSE",
        "third_party/apparmor-ci/clients-provenance.json",
        "third_party/apparmor-ci/provenance.json",
        "third_party/eccodes-sources.json",
        "third_party/hosted-runtime-inputs.json",
        "third_party/hosted-runtime-npm.json",
        HELPER,
    ),
}

# Reviewed declarative JSON bytes; actual download/runtime validation remains
# with the existing preparation scripts. A pin update requires source review.
PIN_SHA256 = {
    "integrations/drizzli/build-plugins.json":
        "8aa2273956b89106f63d84ce82606b723e24f968b297cbc39723812a44201b56",
    "integrations/drizzli/upstream.json":
        "c336f3ac90542f731525ef6cd976be311c76f7c1208bd202308af7ead6d17767",
    "integrations/overmorrow/upstream.json":
        "0b6408c94e50397f31de6bdd22ddda7a62b237245f4be4e69cc92c97a6a2003e",
    "third_party/eccodes-sources.json":
        "f136020562a6ff0d2a83b948189c31f839afb8a00ea87565469f38640fb0dc86",
    "third_party/hosted-runtime-inputs.json":
        "8d122cd42bc2e3eca7c040ae5e847dc5b14e91ac7f30b508fc25beb5f5e860aa",
    "third_party/hosted-runtime-npm.json":
        "5c6ade420006e9754dfb27c81b76846ee82fca17e67f03b4849b7310215e133b",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_paths(profile):
    require(profile in PROFILES, "Unknown source profile")
    paths = PROFILES[profile]
    require(0 < len(paths) <= MAX_FILES and len(set(paths)) == len(paths),
            "Duplicate or oversized source selection")
    for name in paths:
        require(isinstance(name, str) and len(name) <= 256
                and re.fullmatch(r"[A-Za-z0-9_.@/-]+", name)
                and not PurePosixPath(name).is_absolute()
                and all(part not in ("", ".", "..") for part in name.split("/")),
                "Unsafe source path")
    return tuple(sorted(paths))


def safe_info(info, directory=False):
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.getuid() and not info.st_mode & 0o7022
            and (directory or info.st_nlink == 1),
            "Unsafe owned directory/file, mode or hardlink")


def check_root(root):
    require(root.is_absolute(), "Source root must be absolute")
    # Reject symlinks even above the checkout, without forbidding /tmp fixtures.
    for component in (*reversed(root.parents), root):
        require(not component.is_symlink(), "Symlink in source root")
    safe_info(root.lstat(), directory=True)


def read_source(root, name):
    """Walk with directory descriptors; never follow replaced parents or FIFOs."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        safe_info(os.fstat(directory), directory=True)
        parts = name.split("/")
        for part in parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=directory)
            os.close(directory)
            directory = next_directory
            safe_info(os.fstat(directory), directory=True)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            safe_info(before)
            require(before.st_size <= MAX_FILE, "Oversized source file")
            data = stream.read(MAX_FILE + 1)
            after = os.fstat(stream.fileno())
            require(file_state(before) == file_state(after) and len(data) == before.st_size,
                    "Source changed while reading")
            require(file_state(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False))
                    == file_state(after),
                    "Source replaced while reading")
            return data
    finally:
        os.close(directory)


def file_state(info):
    # Reading may change atime; inode/content/authority metadata must not change.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid,
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def git_read(root, args, limit):
    # Only fixed read-only invocations below; no shell, user config, replacements,
    # hooks, optional locks, network or selected source execution.
    environment = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1",
                   "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    with tempfile.TemporaryFile(dir=root / "build") as output, \
            tempfile.TemporaryFile(dir=root / "build") as errors:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root),
                                 *args], stdout=output, stderr=errors,
                                env=environment, timeout=10, check=False)
        require(result.returncode == 0, "Read-only source Git check failed")
        require(output.tell() <= limit, "Oversized Git response")
        output.seek(0)
        return output.read(limit + 1)


def snapshot(root, profile, expected_commit):
    require(isinstance(expected_commit, str)
            and re.fullmatch(r"[0-9a-f]{40}", expected_commit), "Expected commit must be 40 hex")
    check_root(root)
    paths = source_paths(profile)
    head = git_read(root, ["rev-parse", "--verify", "HEAD"], 41).decode().strip()
    require(head == expected_commit, "HEAD differs from expected commit")
    tree = git_read(root, ["ls-tree", "-l", "-z", expected_commit, "--", *paths], MAX_FILES * 512)
    tracked = {}
    for entry in tree.rstrip(b"\0").split(b"\0"):
        require(entry, "Missing tracked source")
        metadata, name = entry.decode("ascii").split("\t", 1)
        mode, kind, oid, size = metadata.split()
        require(name in paths and name not in tracked and mode in ("100644", "100755")
                and kind == "blob" and re.fullmatch(r"[0-9a-f]{40}", oid)
                and size.isdigit() and int(size) <= MAX_FILE, "Unsafe tracked source")
        tracked[name] = (oid, int(size))
    require(set(tracked) == set(paths), "Source selection is not exactly tracked at HEAD")
    files = {}
    for name in paths:
        data = read_source(root, name)
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data,
                           usedforsecurity=False).hexdigest()
        require((oid, len(data)) == tracked[name], "Selected source differs from HEAD: " + name)
        files[name] = data
        require(sum(map(len, files.values())) <= MAX_TOTAL, "Oversized source selection")
    require(git_read(root, ["rev-parse", "--verify", "HEAD"], 41).decode().strip() == head,
            "HEAD changed while reading")
    return files


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def pin_json(files, name):
    raw = files[name]
    require(len(raw) <= 32768, "Oversized dependency pin")
    value = json.loads(raw, object_pairs_hook=unique_pairs,
                       parse_constant=lambda _: require(False, "Non-finite JSON field"))
    require(type(value) is dict and hashlib.sha256(raw).hexdigest() == PIN_SHA256[name],
            "Dependency pin differs from reviewed source")
    return value


def external_references(files, profile):
    prefix = "integrations/" + profile + "/"
    pin = pin_json(files, prefix + "upstream.json")
    require(hashlib.sha256(files[prefix + "upstream.patch"]).hexdigest()
            == pin["upstream_patch_sha256"], "Upstream patch mismatch")
    fields = ["origin", "commit", "tree", "license", "license_sha256", "upstream_patch_sha256"]
    references = {
        "upstream": {"delivery": "references_only", **{key: pin[key] for key in fields}},
        "browser_helpers": {"delivery": "references_only",
                            "origin": "https://github.com/VOLPAROSSA/volparossa-browser",
                            "commit": BROWSER_COMMIT},
    }
    if profile == "drizzli":
        modules = ("src/forecast.mjs", "src/provider.mjs", "src/air-quality.mjs",
                   "src/air-quality-provider.mjs")
        require(type(pin["weather_modules"]) is dict and set(pin["weather_modules"]) == set(modules),
                "Expected exactly four Weather module pins")
        require(all(hashlib.sha256(files[name]).hexdigest() == pin["weather_modules"][name]
                    for name in modules), "Weather module mismatch")
        references["upstream"]["package_lock_sha256"] = pin["package_lock_sha256"]
        references["build_plugins"] = {
            "delivery": "references_only",
            "plugins": pin_json(files, prefix + "build-plugins.json")["plugins"],
        }
    else:
        # Inspect constant AST values only, never import/execute the SDK helper.
        wanted = {"VERSION": pin["flutter"], "COMMIT": pin["flutter_commit"],
                  "ARCHIVE_SHA": pin["flutter_archive_sha256"]}
        constants = {}
        for node in ast.parse(files["scripts/prepare_hosted_flutter.py"]).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in wanted:
                        require(target.id not in constants and isinstance(node.value, ast.Constant),
                                "Invalid Flutter constant")
                        constants[target.id] = node.value.value
        require(constants == wanted, "Flutter source pin mismatch")
        references["upstream"]["pubspec_lock_sha256"] = pin["pubspec_lock_sha256"]
        references["flutter"] = {"delivery": "references_only", **{
            key: pin[key] for key in ("flutter", "flutter_commit", "flutter_archive_sha256")}}
    for label, name in (("decoder_sources", "third_party/eccodes-sources.json"),
                        ("runner_runtimes", "third_party/hosted-runtime-inputs.json"),
                        ("runner_npm", "third_party/hosted-runtime-npm.json")):
        references[label] = {"delivery": "references_only", "pin": pin_json(files, name)}
    require(references["runner_npm"]["pin"]["node_archive_sha256"]
            == references["runner_runtimes"]["pin"]["artifacts"]["node"]["sha256"],
            "Node/npm pin mismatch")
    return references


def manifest_bytes(profile, expected_commit, files):
    require(set(files) == set(source_paths(profile)), "Unexpected manifest source selection")
    manifest = {
        "schema": SCHEMA, "kind": "volparossa-weather-source-recipe", "profile": profile,
        "expected_weather_commit": expected_commit, "actual_weather_commit": expected_commit,
        "helper": {"path": HELPER, "schema": SCHEMA,
                   "sha256": hashlib.sha256(files[HELPER]).hexdigest()},
        "source_files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                         for name, data in sorted(files.items())},
        "external_references": external_references(files, profile),
        "scope": {"source_recipe_only": True, "upstream_sources_included": False,
                  "dependency_sources_included": False, "binary_outputs_included": False,
                  "historical_admission_compatible": False, "runtime_verified": False,
                  "redistribution_cleared": False, "complete_build_recipe_proven": False,
                  "bit_reproducibility_proven": False},
    }
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    require(len(raw) <= MAX_MANIFEST, "Oversized source manifest")
    return raw


def output_path(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    require(path.parent == root / "build"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", path.name),
            "Output must be a new direct child of this checkout's build/")
    check_root(root)
    safe_info((root / "build").lstat(), directory=True)
    require(not path.exists() and not path.is_symlink(), "Output already exists")
    return path


def write_private(path, data, *, dir_fd=None):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=dir_fd)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


def same_output(parent_fd, name, output_fd):
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    own = os.fstat(output_fd)
    return stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (own.st_dev, own.st_ino)


def source_parent(output_fd, name):
    directory = os.dup(output_fd)
    try:
        for part in ("source/" + name).split("/")[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=directory)
            os.close(directory)
            directory = next_directory
            safe_info(os.fstat(directory), directory=True)
        return directory
    except BaseException:
        os.close(directory)
        raise


def clean_output(parent_fd, name, output_fd):
    # A replaced/moved root is interference: preserve the replacement AND the
    # partial original. Never recursively delete using the mutable output name.
    if not same_output(parent_fd, name, output_fd):
        return
    for child in os.listdir(output_fd):
        info = os.stat(child, dir_fd=output_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(child, dir_fd=output_fd)
        else:
            os.unlink(child, dir_fd=output_fd)
    if same_output(parent_fd, name, output_fd):
        # rmdir cannot delete contents of a replacement raced in after this
        # check; recursive cleanup above stays bound to our opened directory.
        os.rmdir(name, dir_fd=parent_fd)


def prepare(root, profile, expected_commit, output):
    path = output_path(root, output)
    files = snapshot(root, profile, expected_commit)
    manifest = manifest_bytes(profile, expected_commit, files)
    # All preflight checks precede creation; mkdir never replaces existing data.
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    output_fd = None
    cleanup_owned = False
    try:
        safe_info(os.fstat(parent_fd), directory=True)
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        output_fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent_fd)
        safe_info(os.fstat(output_fd), directory=True)
        # A prepopulated replacement between mkdir/open is not our output.
        # Do not accept cleanup ownership until acquisition checks succeed.
        require(not os.listdir(output_fd), "New output directory is not empty; preserve unowned output")
        require(same_output(parent_fd, path.name, output_fd), "Output changed during acquisition; preserve unowned output")
        cleanup_owned = True
        for name, data in files.items():
            require(same_output(parent_fd, path.name, output_fd), "Output directory was replaced; partial preserved")
            destination_fd = source_parent(output_fd, name)
            try:
                write_private(name.split("/")[-1], data, dir_fd=destination_fd)
            finally:
                os.close(destination_fd)
        require(snapshot(root, profile, expected_commit) == files,
                "Selected source changed before completion")
        require(same_output(parent_fd, path.name, output_fd), "Output directory was replaced; partial preserved")
        write_private("manifest.json", manifest, dir_fd=output_fd)
        require(same_output(parent_fd, path.name, output_fd), "Output directory was replaced; partial preserved")
    except BaseException:
        if cleanup_owned:
            clean_output(parent_fd, path.name, output_fd)
        raise
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(parent_fd)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    prepare(ROOT, args.profile, args.expected_commit, args.output)
    print("Prepared source recipe only; runtime, consumer admission and redistribution remain unverified.")


if __name__ == "__main__":
    main()
