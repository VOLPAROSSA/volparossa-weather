# SPDX-License-Identifier: GPL-3.0-only
"""Inert checks for the hosted client workflow's source and export boundary."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hosted-clients.yml"


class HostedClientWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()

    def test_exact_public_checkouts_and_read_only_permissions(self):
        actions = re.findall(r"uses: ([^\s]+)", self.source)
        self.assertTrue(actions)
        for action in actions:
            self.assertRegex(action, r"^[\w/-]+@[0-9a-f]{40}$")
        self.assertEqual(self.source.count("persist-credentials: false"), 2)
        self.assertIn("repository: VOLPAROSSA/volparossa-browser", self.source)
        self.assertIn("ref: 08bac388a0abfd06426bebe8f6fabd0157d2e709", self.source)
        self.assertIn("permissions:\n  contents: read\n", self.source)
        self.assertNotIn("secrets.", self.source)
        self.assertNotIn("github.token", self.source)

    def test_bounded_explicit_disposable_execution(self):
        self.assertIn("runs-on: ubuntu-24.04", self.source)
        self.assertIn("timeout-minutes: 30", self.source)
        self.assertIn('test "$RUNNER_ENVIRONMENT" = github-hosted', self.source)
        self.assertIn("cancel-in-progress: false", self.source)
        self.assertIn("scripts/prepare_hosted_runtime.py --with-npm --fetch", self.source)
        self.assertIn("python3 -B scripts/prepare_hosted_clients_ci.py", self.source)
        self.assertNotIn("npm run build", self.source)
        self.assertNotIn("curl |", self.source)
        self.assertNotIn("sysctl -w", self.source)

    def test_export_only_public_successful_inputs_and_bounded_diagnostics(self):
        assets = self.source.split("- name: Retain only successful public assets and original notices\n", 1)[1]
        assets = assets.split("- name: State the scope", 1)[0]
        self.assertIn("if: success()", assets)
        self.assertIn("build/drizzli-hosted-ci/build", assets)
        self.assertIn("build/hosted-client-runtime/node/LICENSE", assets)
        for forbidden in ("node_modules", "archives", ".git/", "inputs.tar", "profile/", "**", "~", "/home/"):
            self.assertNotIn(forbidden, assets)
        self.assertNotRegex(self.source, r"(?m)^\s+build/?\s*$")
        self.assertIn("build/drizzli-hosted-browser-ci/report.json", self.source)
        self.assertIn("core input profile before joined execution", self.source)

    def test_embedded_shell_syntax(self):
        blocks = re.findall(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", self.source)
        self.assertEqual(len(blocks), 5)
        for block in blocks:
            script = "\n".join(line[10:] for line in block.splitlines())
            result = subprocess.run(["bash", "-n"], input=script, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
