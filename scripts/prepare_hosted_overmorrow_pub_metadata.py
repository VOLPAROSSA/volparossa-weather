#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Pure validation of the pinned Overmorrow app-pub metadata, without I/O.

The caller authenticates both roots, the original SDK manifest engineRevision,
and the supplied cache-format digests before calling this function. Metadata
never supplies paths to open. Cache digests grant no source authority.
This checks metadata consistency, not generated Dart semantics or admission.

Producer: Flutter f6ff1529fd6d8af5f706051d9251ac9231c83407, with original
Overmorrow 97995e2e00e454389e00e35f1e65654afe3e8bed and its unchanged l10n.yaml.
The fixed locale roles follow gen_l10n.dart and the original 36 ARBs; regional
classes pt_BR and zh_Hant are embedded in the base-language output files.
"""
import hashlib
import json
import re
import struct

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

# The bookkeeping hash below translates the pinned Flutter implementation,
# including its nonstandard final padding. Keep the original notice unchanged.
FLUTTER_HASH_SOURCE_SHA256 = '78abfb964a4611e1ce81ee53b44245c291229a80e27d6536e0890ca651ac549d'
FLUTTER_HASH_LICENSE_SHA256 = 'a598db94b6290ffbe10b5ecf911057b6a943351c727fdda9e5f2891d68700a20'
FLUTTER_HASH_LICENSE = '''Copyright 2014 The Flutter Authors. All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
      copyright notice, this list of conditions and the following
      disclaimer in the documentation and/or other materials provided
      with the distribution.
    * Neither the name of Google Inc. nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''
_NOISE = (
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
)
_SHIFTS = (7, 12, 17, 22) * 4 + (5, 9, 14, 20) * 4 + (4, 11, 16, 23) * 4 + (6, 10, 15, 21) * 4


def _cache_block(state, block):
    words = struct.unpack('<16I', block)
    a, b, c, d = state
    mask = 0xffffffff
    for index in range(64):
        if index < 16:
            value, word = (b & c) | ((~b & mask) & d), index
        elif index < 32:
            value, word = (d & b) | ((~d & mask) & c), (5 * index + 1) % 16
        elif index < 48:
            value, word = b ^ c ^ d, (3 * index + 5) % 16
        else:
            value, word = c ^ (b | (~d & mask)), (7 * index) % 16
        value = (a + value + _NOISE[index] + words[word]) & mask
        shift = _SHIFTS[index]
        rotated = ((value << shift) | (value >> (32 - shift))) & mask
        a, b, c, d = d, (b + rotated) & mask, b, c
    return tuple((old + new) & mask for old, new in zip(state, (a, b, c, d)))


def cache_hash(raw):
    """Match original FileStore Md5Hash on the fixed little-endian amd64 SDK.

    FileStore uses a fresh hasher and 64 KiB reads. Those reads are multiples
    of 64, so processing the same full blocks followed by the final tail is
    equivalent. No claim covers arbitrary Dart views or partial read schedules.
    This deliberately retains the original one-block finalization at tail
    lengths 56..63. It is not ordinary MD5 and must never replace SHA256 checks.
    """
    need(type(raw) is bytes and len(raw) <= MAX_FILE, 'P15_PUB_METADATA_HASH_BOUND')
    state = (0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476)
    whole = len(raw) // 64 * 64
    for start in range(0, whole, 64):
        state = _cache_block(state, raw[start:start + 64])
    tail = bytearray(64)
    remaining = len(raw) - whole
    tail[:remaining] = raw[whole:]
    tail[remaining] = 0x80
    remaining += 1
    zeroes = 56 - remaining
    for index in range(remaining, zeroes):
        tail[index] = 0
    struct.pack_into('<Q', tail, 56, len(raw) * 8)
    return struct.pack('<4I', *_cache_block(state, tail)).hex()


def _invalid_digest_summary(value):
    """Fingerprint an invalid JSON value without recursion or raw projection."""
    types = {str: 'string', type(None): 'null', bool: 'boolean', int: 'integer',
             list: 'array', dict: 'object'}
    need(type(value) in types, 'P15_PUB_METADATA_CACHE_DIAGNOSTIC')
    if type(value) is str:
        raw = value.encode('utf-8', errors='surrogatepass')
        length, digest = len(raw), hashlib.sha256(raw).hexdigest()
    else:
        stack, length, hasher, visited = [value], 0, hashlib.sha256(), 0
        while stack:
            item = stack.pop()
            visited += 1
            need(visited <= MAX_FILE * 3, 'P15_PUB_METADATA_CACHE_DIAGNOSTIC_BOUND')
            if type(item) is bytes:
                raw = item  # Internal punctuation only; JSON values cannot be bytes.
            elif type(item) is list:
                stack.append(b']')
                for index in range(len(item) - 1, -1, -1):
                    stack.append(item[index])
                    if index:
                        stack.append(b',')
                raw = b'['
            elif type(item) is dict:
                names = sorted(item)
                stack.append(b'}')
                for index in range(len(names) - 1, -1, -1):
                    stack.extend((item[names[index]], b':', names[index]))
                    if index:
                        stack.append(b',')
                raw = b'{'
            else:
                need(type(item) in (str, type(None), bool, int), 'P15_PUB_METADATA_CACHE_DIAGNOSTIC')
                raw = json.dumps(item, ensure_ascii=True, separators=(',', ':')).encode('ascii')
            length += len(raw)
            need(length <= MAX_FILE * 6, 'P15_PUB_METADATA_CACHE_DIAGNOSTIC_BOUND')
            hasher.update(raw)
        digest = hasher.hexdigest()
    need(length <= MAX_FILE * 6, 'P15_PUB_METADATA_CACHE_DIAGNOSTIC_BOUND')
    return dict(observed_type=types[type(value)], observed_length=length, observed_sha256=digest)


class CacheHashFailure(ValueError):
    """Closed, bounded cache-only diagnostic; never a hook observation."""
    def __init__(self, mismatches):
        super().__init__('P15_PUB_METADATA_CACHE_HASH')
        need(type(mismatches) is list and 0 < len(mismatches) <= 73,
             'P15_PUB_METADATA_CACHE_DIAGNOSTIC')
        allowed = {('input', 'sdk-target'), ('input', 'l10n.yaml')}
        allowed.update(('input', path) for path in ARBS)
        allowed.update(('output', path) for path in OUTPUTS)
        rows, seen = [], set()
        for role, label, expected, observed in mismatches:
            need((role, label) in allowed and (role, label) not in seen
                 and type(expected) is str and re.fullmatch('[0-9a-f]{32}', expected) is not None,
                 'P15_PUB_METADATA_CACHE_DIAGNOSTIC')
            seen.add((role, label))
            row = dict(role=role, label=label, expected_digest=expected)
            if type(observed) is str and re.fullmatch('[0-9a-f]{32}', observed) is not None:
                row['observed_digest'] = observed
            else:
                row.update(_invalid_digest_summary(observed))
            rows.append(tuple(row.items()))
        self._rows = tuple(rows)

    def cache_observation(self):
        return dict(metadata_file='.filecache', algorithm='flutter-3.38.5-Md5Hash',
                    entries_checked=73, mismatch_count=len(self._rows),
                    mismatches=[dict(row) for row in self._rows])


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
    cover 38 inputs (SDK target, l10n.yaml, 36 ARBs) and 35 generated outputs using
    cache_hash(), not ordinary MD5. The build identifier still uses standard MD5.
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
        observed[path] = item['hash']
    need(set(observed) == set(expected_hashes), 'P15_PUB_METADATA_CACHE_ENTRIES')
    roles = [(inputs[0], 'input', 'sdk-target')]
    roles += [(path, 'input', path[len(app_root) + 1:]) for path in dep_inputs]
    roles += [(path, 'output', path[len(app_root) + 1:]) for path in outputs]
    mismatches = [(role, label, expected_hashes[path], observed[path])
                  for path, role, label in roles if observed[path] != expected_hashes[path]]
    if mismatches:
        raise CacheHashFailure(mismatches)

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
