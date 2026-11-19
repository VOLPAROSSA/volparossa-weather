# SPDX-License-Identifier: GPL-3.0-only
"""Install the reviewed Apple Silicon bottles and verify the original Debian image."""
from pathlib import Path
import json
import os
import subprocess
import sys

from media import BASE, DEBIAN, digest

bottles = {'qemu': ('11.1.3', 'a99cca4450c91f471e8e546b8fb48780e0cb2104ffbe15d394c1b431d44df620'),
           'xcodegen': ('2.47.0', '779520cbf1a63446071de85458a09a2966f0e40e2671e285920f8c46ec544c64')}
assert os.environ['RUNNER_ENVIRONMENT'] == 'github-hosted' and os.uname().machine == 'arm64'
for spec in json.loads(subprocess.check_output(['brew', 'info', '--json=v2', *bottles]))['formulae']:
    version, sha = bottles[spec['name']]
    assert spec['versions']['stable'] == version and spec['bottle']['stable']['files']['arm64_sequoia']['sha256'] == sha, spec['name']
subprocess.run(['brew', 'install', '--formula', *bottles], check=True, env={**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1'})
assert 'version 11.1.3' in subprocess.check_output(['qemu-system-x86_64', '--version'], text=True)
assert '2.47.0' in subprocess.check_output(['xcodegen', '--version'], text=True)
image = Path(sys.argv[1]) / 'base.qcow2'
subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https',
                '--max-redirs', '3', '--connect-timeout', '30', '--max-time', '600', '--max-filesize', '2147483648',
                '--output', image, BASE], check=True)
assert digest(image, 'sha512') == DEBIAN
