# SPDX-License-Identifier: GPL-3.0-only
"""Bind public input media and the distribution image to the exact same workflow run."""
from pathlib import Path
import hashlib
import json
import os
import sys

CORE = '3cccff9190126e1b4bb76504aa2932735f523ea3'
DEBIAN = '184761b0dad0f9ace02f9298050ca96ce3caa39a461a47706d47ff9698b59933918b91b40177fbd4d392f6446af8b4d18ecb94caca988169b19641606bf34003'
BASE = 'https://cloud.debian.org/images/cloud/trixie/20260826-2582/debian-13-genericcloud-amd64-20260826-2582.qcow2'


def digest(path, algorithm='sha256'):
    with path.open('rb') as source:
        return hashlib.file_digest(source, algorithm).hexdigest()


def media(directory):
    hashes = {}
    for name in ('seed.img', 'data.iso'):
        path = directory / name
        assert not path.is_symlink() and path.is_file() and 0 < path.stat().st_size < 512 * 1024**2
        hashes[name] = digest(path)
    return dict(core=CORE, weather=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'],
                debian_sha512=DEBIAN, image=BASE, files=hashes)


if __name__ == '__main__':
    operation, directory = sys.argv[1], Path(sys.argv[2])
    result = media(directory)
    if operation == 'write':
        spec = json.loads(Path('build/core/tests/helper/debian13-amd64-image-v1.json').read_bytes())
        assert spec['url'] == BASE and spec['sha512'] == DEBIAN and CORE == os.environ['CORE_SOURCE']
        (directory / 'media.json').write_text(json.dumps(result, sort_keys=True) + '\n')
    elif operation == 'verify':
        assert {p.name for p in directory.iterdir()} == {'seed.img', 'data.iso', 'media.json'}
        assert json.loads((directory / 'media.json').read_bytes()) == result
    else:
        raise ValueError(operation)
