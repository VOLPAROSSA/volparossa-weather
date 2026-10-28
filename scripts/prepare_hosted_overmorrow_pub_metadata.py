#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Pure validation of the pinned Overmorrow app-pub metadata, without I/O.

The caller authenticates both roots, the original SDK manifest engineRevision,
and the supplied file MD5s before calling this function. Metadata never supplies
paths to open. MD5 matches Flutter's cache format; it grants no source authority.
This checks metadata consistency, not generated Dart semantics or admission.

Producer: Flutter f6ff1529fd6d8af5f706051d9251ac9231c83407, with original
Overmorrow 97995e2e00e454389e00e35f1e65654afe3e8bed and its unchanged l10n.yaml.
The fixed locale roles follow gen_l10n.dart and the original 36 ARBs; regional
classes pt_BR and zh_Hant are embedded in the base-language output files.
"""
import hashlib
import json
import re

MAX_FILE = 1024 * 1024
MAX_TOTAL = 4 * MAX_FILE
SDK_TARGET = '/packages/flutter_tools/lib/src/build_system/targets/localizations.dart'
LOCALES = tuple(('ar bg bn ca da de el en es fi fr he hr hu id it ja mk nl pl pt '
                 'pt_BR ro ru sk sl sr sw ta tr uk ur uz vi zh zh_Hant').split())
ARBS = tuple('lib/l10n/app_' + locale + '.arb' for locale in LOCALES)
OUTPUTS = tuple('lib/l10n/app_localizations_' + locale + '.dart'
                for locale in LOCALES if '_' not in locale) + ('lib/l10n/app_localizations.dart',)
LEAVES = frozenset(('.filecache', 'gen_l10n_inputs_and_outputs.json',
                    'gen_localizations.d', 'gen_localizations.stamp', 'outputs.json'))


def need(condition, code):
    if not condition:
        raise ValueError(code)


def absolute(path):
    need(type(path) is str and 0 < len(path) <= 4096 and path.startswith('/')
         and '\\' not in path and all(32 <= ord(c) < 127 for c in path),
         'P15_PUB_METADATA_ROOT')
    parts = path.split('/')[1:]
    need(0 < len(parts) <= 64 and all(part not in ('', '.', '..') for part in parts),
         'P15_PUB_METADATA_ROOT')


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'P15_PUB_METADATA_JSON_DUPLICATE')
        result[key] = value
    return result


def integer(value):
    need(len(value) <= 16, 'P15_PUB_METADATA_JSON_NUMBER')
    return int(value)


def document(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                          parse_int=integer,
                          parse_float=lambda _: need(False, 'P15_PUB_METADATA_JSON_NUMBER'),
                          parse_constant=lambda _: need(False, 'P15_PUB_METADATA_JSON_NUMBER'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('P15_PUB_METADATA_JSON') from None


def keys(value, expected):
    need(type(value) is dict and set(value) == set(expected), 'P15_PUB_METADATA_KEYS')


def members(value, expected):
    need(type(value) is list and len(value) == len(expected)
         and all(type(item) is str for item in value), 'P15_PUB_METADATA_MEMBERS')
    need(len(set(value)) == len(value) and set(value) == set(expected),
         'P15_PUB_METADATA_MEMBERS')


def hashes(value, expected):
    need(type(value) is dict and len(value) == len(expected)
         and all(type(path) is str for path in value) and set(value) == set(expected),
         'P15_PUB_METADATA_HASH_PATHS')
    for path, checksum in value.items():
        absolute(path)
        need(type(checksum) is str and re.fullmatch('[0-9a-f]{32}', checksum) is not None,
             'P15_PUB_METADATA_MD5')


def escape(path):
    return path.replace('\\', '/').replace(' ', '\\ ')


def validate(files, *, app_root, sdk_root, engine_revision, input_hashes, output_hashes):
    """Validate six private byte strings against separately authenticated data.

    Only the successful first app-pub state is accepted. The exact bound hashes
    cover 38 inputs (SDK target, l10n.yaml, 36 ARBs) and 35 generated outputs.
    Nothing is read, executed, or admitted by this function. Errors contain only
    fixed codes, and the receipt contains no raw paths or artifact contents.
    """
    absolute(app_root)
    absolute(sdk_root)
    need(app_root != sdk_root and not app_root.startswith(sdk_root + '/')
         and not sdk_root.startswith(app_root + '/'), 'P15_PUB_METADATA_ROOT_OVERLAP')
    need(type(engine_revision) is str and re.fullmatch('[0-9a-f]{40}', engine_revision) is not None,
         'P15_PUB_METADATA_ENGINE')
    build_id = hashlib.md5((engine_revision + 'build').encode(), usedforsecurity=False).hexdigest()
    prefix = 'build/' + build_id + '/'
    expected_files = {prefix + leaf for leaf in LEAVES} | {'build/.last_build_id'}
    need(type(files) is dict and len(files) == 6
         and all(type(name) is str for name in files) and set(files) == expected_files,
         'P15_PUB_METADATA_FILES')
    need(all(type(raw) is bytes and 0 < len(raw) <= MAX_FILE for raw in files.values())
         and sum(len(raw) for raw in files.values()) <= MAX_TOTAL, 'P15_PUB_METADATA_BOUND')

    arbs = [app_root + '/' + path for path in ARBS]
    outputs = [app_root + '/' + path for path in OUTPUTS]
    dep_inputs = [app_root + '/l10n.yaml', *arbs]
    inputs = [sdk_root + SDK_TARGET, *dep_inputs]
    hashes(input_hashes, inputs)
    hashes(output_hashes, outputs)

    generated = document(files[prefix + 'gen_l10n_inputs_and_outputs.json'])
    keys(generated, ('inputs', 'outputs'))
    members(generated['inputs'], arbs)
    members(generated['outputs'], outputs)

    stamp = document(files[prefix + 'gen_localizations.stamp'])
    keys(stamp, ('inputs', 'outputs'))
    members(stamp['inputs'], inputs)
    members(stamp['outputs'], outputs)
    members(document(files[prefix + 'outputs.json']), outputs)

    cache = document(files[prefix + '.filecache'])
    keys(cache, ('version', 'files'))
    need(type(cache['version']) is int and cache['version'] == 2,
         'P15_PUB_METADATA_CACHE_VERSION')
    need(type(cache['files']) is list and len(cache['files']) == 73,
         'P15_PUB_METADATA_CACHE_ENTRIES')
    expected_hashes = dict(input_hashes, **output_hashes)
    observed = {}
    for item in cache['files']:
        keys(item, ('path', 'hash'))
        path = item['path']
        need(type(path) is str and path in expected_hashes and path not in observed,
             'P15_PUB_METADATA_CACHE_PATH')
        need(type(item['hash']) is str and item['hash'] == expected_hashes[path],
             'P15_PUB_METADATA_CACHE_HASH')
        observed[path] = item['hash']
    need(observed == expected_hashes, 'P15_PUB_METADATA_CACHE_ENTRIES')

    depfile = (''.join(' ' + escape(path) for path in outputs) + ': '
               + ''.join(' ' + escape(path) for path in dep_inputs)).encode()
    need(files[prefix + 'gen_localizations.d'] == depfile, 'P15_PUB_METADATA_DEPFILE')
    need(files['build/.last_build_id'] == build_id.encode(), 'P15_PUB_METADATA_BUILD_ID')
    inventory = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    digest = hashlib.sha256((json.dumps(inventory, sort_keys=True, separators=(',', ':'))
                             + '\n').encode()).hexdigest()
    return dict(schema=1, kind='overmorrow-pub-metadata-consistency', admitted=False,
                metadata_files=6, inputs=38, outputs=35, cache_entries=73,
                metadata_bytes=sum(len(raw) for raw in files.values()), metadata_sha256=digest)
