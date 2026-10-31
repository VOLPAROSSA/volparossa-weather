#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Closed first-post-pub source validation, without execution or release authority.

The caller authenticates the authorization record and calls the existing complete
dependency and plugin binders BEFORE this validator. They remain responsible for
package-config/graph semantics and exact plugin identities, roots and targets.
Only Inventory's descriptor-bound private byte reader touches source files here.
No policy or diagnostic observation grants executable or production admission.
"""
import datetime
import hashlib
import json
from pathlib import PurePosixPath
import re

BEFORE_SHA = '94a0f9632f425453887f41b8b3e9926e3d4c3516f3fd4ce3d8db1540d7e48baf'
PRODUCERS_SHA = '5dfda4d8a1716b798f9c3b5979cd18b3a7b3c7256304d5a2f8f3c4556d2918f9'
METADATA_CATALOGUE_SHA = 'bc96728fd748e61420e3e9770035ddee8fac535f8e2e32b143d3c6d7f4c2b561'
SDK_INVENTORY_SHA = '98df602485d0dd66195f614e950dc59ed3f7dddf5169431ece5a4c2a92ace5c7'
SDK_MANIFEST_SHA = 'd7a750731cead19d1c5f931a5ca0a3a4dee1fb3829f3713465abd478b405537c'
SDK_TARGET_SHA = '2f8145786bbc9ce7f14a647cc40a407be87f5f3b596bd77a0f16f5233626c430'
SDK_TARGET = '/packages/flutter_tools/lib/src/build_system/targets/localizations.dart'
LOCALES = tuple(('ar bg bn ca da de el en es fi fr he hr hu id it ja mk nl pl pt '
                 'pt_BR ro ru sk sl sr sw ta tr uk ur uz vi zh zh_Hant').split())
ARBS = frozenset('lib/l10n/app_' + locale + '.arb' for locale in LOCALES)
L10N_OUTPUTS = frozenset('lib/l10n/app_localizations_' + locale + '.dart'
                         for locale in LOCALES if '_' not in locale) | {'lib/l10n/app_localizations.dart'}
MANIFEST = '.flutter-plugins-dependencies'
GENERATED = L10N_OUTPUTS | frozenset((MANIFEST,
    'android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java', 'android/local.properties',
    'ios/Flutter/Generated.xcconfig', 'ios/Flutter/ephemeral/flutter_lldb_helper.py',
    'ios/Flutter/ephemeral/flutter_lldbinit', 'ios/Flutter/flutter_export_environment.sh',
    'ios/Runner/GeneratedPluginRegistrant.h', 'ios/Runner/GeneratedPluginRegistrant.m',
    'macos/Flutter/GeneratedPluginRegistrant.swift', 'macos/Flutter/ephemeral/Flutter-Generated.xcconfig',
    'macos/Flutter/ephemeral/flutter_export_environment.sh',
    *(platform + '/flutter/' + leaf for platform in ('linux', 'windows') for leaf in
      ('generated_plugin_registrant.cc', 'generated_plugin_registrant.h', 'generated_plugins.cmake'))))
DART_TOOL = {'.dart_tool/package_config.json': 'package_config',
             '.dart_tool/package_graph.json': 'package_graph', '.dart_tool/version': 'flutter_version',
             '.dart_tool/dartpad/web_plugin_registrant.dart': 'dartpad'}
DARTPAD = '.dart_tool/dartpad/web_plugin_registrant.dart'
METADATA_LEAVES = frozenset(('.filecache', 'gen_l10n_inputs_and_outputs.json',
                            'gen_localizations.d', 'gen_localizations.stamp', 'outputs.json'))
METADATA_PATHS = {'build/<pub-build-id>/' + leaf for leaf in METADATA_LEAVES} | {'build/.last_build_id'}
ALIASES = frozenset(platform + '/flutter/ephemeral/.plugin_symlinks/' + name
    for platform in ('linux', 'windows') for name in
    ('dynamic_system_colors', 'flutter_local_notifications_' + platform, 'geolocator_' + platform,
     'jni', 'package_info_plus', 'path_provider_' + platform, 'shared_preferences_' + platform,
     'url_launcher_' + platform))


def need(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def md5(raw):
    return hashlib.md5(raw, usedforsecurity=False).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'P15_PUB_OUTPUT_JSON_DUPLICATE')
        result[key] = value
    return result


def document(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: need(False, 'P15_PUB_OUTPUT_JSON'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('P15_PUB_OUTPUT_JSON') from None


def mode(value):
    return type(value) is int and 0 <= value <= 0o777 and not value & 0o022


def digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def parents(paths):
    return {str(parent) for name in paths for parent in PurePosixPath(name).parents if str(parent) != '.'}


def policy_contract(policy):
    need(type(policy) is dict and policy.get('schema') == 1
         and policy.get('kind') == 'p15f-controlled-pub-output-authorization'
         and policy.get('before_files_sha256') == BEFORE_SHA
         and policy.get('producer_catalogue_sha256') == PRODUCERS_SHA
         and policy.get('metadata_catalogue_sha256') == METADATA_CATALOGUE_SHA
         and policy.get('sdk_inventory_sha256') == SDK_INVENTORY_SHA, 'P15_PUB_OUTPUT_POLICY')
    generated = policy.get('generated_sources')
    need(type(generated) is dict and set(generated) == GENERATED and len(generated) == 53,
         'P15_PUB_OUTPUT_GENERATED_POLICY')
    for name, row in generated.items():
        need(type(row) is dict and mode(row.get('mode')), 'P15_PUB_OUTPUT_MODE')
        if name == MANIFEST:
            need(set(row) == {'mode', 'role'} and row['role'] == 'plugin_manifest',
                 'P15_PUB_OUTPUT_MANIFEST_POLICY')
        else:
            need(set(row) == {'mode', 'role', 'normalized_sha256', 'root_occurrences'}
                 and row['role'] == 'normalized' and digest(row['normalized_sha256']),
                 'P15_PUB_OUTPUT_NORMALIZED_POLICY')
            counts = row['root_occurrences']
            need(type(counts) is dict and set(counts) == {'app', 'sdk'}
                 and all(type(value) is int and 0 <= value <= 1024**2 for value in counts.values()),
                 'P15_PUB_OUTPUT_NORMALIZED_POLICY')
    tools = policy.get('dart_tool')
    need(type(tools) is dict and set(tools) == set(DART_TOOL), 'P15_PUB_OUTPUT_TOOL_POLICY')
    for name, row in tools.items():
        need(type(row) is dict and row.get('role') == DART_TOOL[name] and mode(row.get('mode'))
             and set(row) == ({'role', 'mode', 'sha256'} if name == DARTPAD else {'role', 'mode'})
             and (name != DARTPAD or digest(row['sha256'])), 'P15_PUB_OUTPUT_TOOL_POLICY')
    metadata = policy.get('metadata_paths')
    need(type(metadata) is dict and set(metadata) == METADATA_PATHS
         and all(mode(value) for value in metadata.values()), 'P15_PUB_OUTPUT_METADATA_POLICY')


def plugin_scalar_contract(raw):
    value = document(raw)
    need(type(value) is dict and set(value) == {'info', 'plugins', 'dependencyGraph', 'date_created',
                                               'version', 'swift_package_manager_enabled'}
         and value['info'] == 'This is a generated file; do not edit or check into version control.'
         and value['version'] == '3.38.5' and type(value['plugins']) is dict
         and set(value['plugins']) == {'ios', 'android', 'macos', 'linux', 'windows', 'web'}
         and type(value['dependencyGraph']) is list, 'P15_PUB_OUTPUT_PLUGIN_SCHEMA')
    stamp = value['date_created']
    need(type(stamp) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}(?:[0-9]{3})?',
                                           stamp) is not None, 'P15_PUB_OUTPUT_PLUGIN_DATE')
    try:
        datetime.datetime.fromisoformat(stamp)
    except ValueError:
        raise ValueError('P15_PUB_OUTPUT_PLUGIN_DATE') from None
    flags = value['swift_package_manager_enabled']
    need(type(flags) is dict and set(flags) == {'ios', 'macos'}
         and all(value is False for value in flags.values()), 'P15_PUB_OUTPUT_SPM')


def validate(inventory, snapshot, before, policy, roots, metadata_validator, sdk_metadata):
    """Validate only the complete first successful app-pub state before fixtures.

    Existing D.verify and plugin binding/seal are mandatory caller prerequisites.
    Their exact roots/schema checks are not substituted by this closed-file proof.
    """
    policy_contract(policy)
    need(type(roots) is dict and set(roots) == {'app', 'sdk'} and roots['app'] == inventory.stage,
         'P15_PUB_OUTPUT_ROOTS')
    need(set(before) >= {'files', 'directories', 'aliases', 'unsafe'} and len(before['files']) == 386
         and not before['aliases'] and not before['unsafe']
         and sha(canonical({name: row['sha256'] for name, row in before['files'].items()})) == BEFORE_SHA,
         'P15_PUB_OUTPUT_BASELINE')
    need(type(sdk_metadata) is dict and set(sdk_metadata) == {'manifest', 'target'}
         and type(sdk_metadata['manifest']) is bytes and len(sdk_metadata['manifest']) <= 16384
         and type(sdk_metadata['target']) is bytes and len(sdk_metadata['target']) <= 1024**2
         and sha(sdk_metadata['manifest']) == SDK_MANIFEST_SHA and sha(sdk_metadata['target']) == SDK_TARGET_SHA,
         'P15_PUB_OUTPUT_SDK_METADATA')
    manifest = document(sdk_metadata['manifest'])
    engine = manifest.get('engineRevision') if type(manifest) is dict else None
    need(type(engine) is str and re.fullmatch('[0-9a-f]{40}', engine) is not None,
         'P15_PUB_OUTPUT_ENGINE')
    build_id = md5((engine + 'build').encode())
    metadata_modes = {name.replace('<pub-build-id>', build_id): value
                      for name, value in policy['metadata_paths'].items()}
    expected = set(before['files']) | GENERATED | set(DART_TOOL) | set(metadata_modes)
    need(not snapshot['unsafe'] and set(snapshot['files']) == expected, 'P15_PUB_OUTPUT_FILE_CLOSURE')
    need(set(snapshot['aliases']) == ALIASES and all(row.get('type') == 'symlink'
         for row in snapshot['aliases'].values()), 'P15_PUB_OUTPUT_ALIAS_CLOSURE')
    expected_dirs = set(before['directories']) | parents(expected | ALIASES)
    need(set(snapshot['directories']) == expected_dirs, 'P15_PUB_OUTPUT_DIRECTORY_CLOSURE')
    need(all(snapshot['directories'][name] == row for name, row in before['directories'].items()),
         'P15_PUB_OUTPUT_ORIGINAL_DIRECTORY')
    need(all(snapshot['files'][name] == row for name, row in before['files'].items()),
         'P15_PUB_OUTPUT_ORIGINAL_CHANGED')
    for names in (policy['generated_sources'], policy['dart_tool']):
        need(all(snapshot['files'][name]['mode'] == row['mode'] for name, row in names.items()),
             'P15_PUB_OUTPUT_MODE')
    need(all(snapshot['files'][name]['mode'] == value for name, value in metadata_modes.items()),
         'P15_PUB_OUTPUT_MODE')
    normalized = inventory.normalized(snapshot, sorted(GENERATED - {MANIFEST}), roots)
    for name, row in normalized.items():
        need(row['normalized_sha256'] == policy['generated_sources'][name]['normalized_sha256']
             and row['root_occurrences'] == policy['generated_sources'][name]['root_occurrences'],
             'P15_PUB_OUTPUT_GENERATED_CHANGED')
    need(set(normalized) == GENERATED - {MANIFEST}, 'P15_PUB_OUTPUT_NORMALIZED_CLOSURE')
    selected = ARBS | L10N_OUTPUTS | {'l10n.yaml', MANIFEST, '.dart_tool/version', DARTPAD} | set(metadata_modes)
    raw = inventory.contents(snapshot, sorted(selected))
    plugin_scalar_contract(raw[MANIFEST])
    need(raw['.dart_tool/version'] == b'3.38.5'
         and sha(raw[DARTPAD]) == policy['dart_tool'][DARTPAD]['sha256'], 'P15_PUB_OUTPUT_TOOL_CONTENT')
    need(set(metadata_validator.ARBS) == ARBS and set(metadata_validator.OUTPUTS) == L10N_OUTPUTS
         and metadata_validator.SDK_TARGET == SDK_TARGET, 'P15_PUB_OUTPUT_METADATA_ROLES')
    # Mirror the original SDK's cache bookkeeping, including its final-block
    # behavior. Full source SHA256 and normalized-output bindings above remain
    # the integrity authority; build-ID derivation still uses ordinary MD5.
    input_hashes = {roots['app'] + '/' + name: metadata_validator.cache_hash(raw[name])
                    for name in ARBS | {'l10n.yaml'}}
    input_hashes[roots['sdk'] + SDK_TARGET] = metadata_validator.cache_hash(sdk_metadata['target'])
    output_hashes = {roots['app'] + '/' + name: metadata_validator.cache_hash(raw[name])
                     for name in L10N_OUTPUTS}
    receipt = metadata_validator.validate({name: raw[name] for name in metadata_modes}, app_root=roots['app'],
        sdk_root=roots['sdk'], engine_revision=engine, input_hashes=input_hashes, output_hashes=output_hashes)
    return dict(schema=1, kind='p15f-first-post-pub-source-validation', admitted=False,
        source_files=len(snapshot['files']), generated_sources=53, dart_tool_files=4, metadata_files=6,
        source_files_sha256=sha(canonical({name: row['sha256'] for name, row in snapshot['files'].items()})),
        metadata=receipt, plugin_manifest_sha256=sha(raw[MANIFEST]),
        existing_dependency_and_plugin_binders_required=True)
