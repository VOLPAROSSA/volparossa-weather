# SPDX-License-Identifier: GPL-3.0-only
"""Inert checks for the hosted client workflow's source and export boundary."""
from pathlib import Path
import re
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hosted-clients.yml"


class HostedClientWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text().split("\n  input-candidate:", 1)[0]

    def test_exact_public_checkouts_and_read_only_permissions(self):
        actions = re.findall(r"uses: ([^\s]+)", self.source)
        self.assertTrue(actions)
        for action in actions:
            self.assertRegex(action, r"^[\w/-]+@[0-9a-f]{40}$")
        self.assertEqual(self.source.count("persist-credentials: false"), 4)
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

    def test_export_only_successful_source_recipe_and_bounded_diagnostics(self):
        assets = self.source.split("- name: Retain only the successful source recipe\n", 1)[1]
        assets = assets.split("- name: State the scope", 1)[0]
        self.assertIn("if: success()", assets)
        self.assertIn("name: hosted-weather-client-source-recipe-${{ github.sha }}", assets)
        self.assertIn("include-hidden-files: true", assets)
        self.assertEqual(self.source.count("include-hidden-files: true"), 1)
        self.assertEqual([line.strip() for line in assets.split("path: |\n", 1)[1].splitlines()
                          if line.strip()], ["build/hosted-drizzli-source-recipe"])
        for forbidden in ("node_modules", "archives", ".git/", "inputs.tar", "profile/", "**", "~", "/home/",
                          "drizzli-hosted-ci/build", "firefox-hosted-ci", "hosted-client-runtime",
                          "assets-unadmitted", "LICENSE", "package-lock.json"):
            self.assertNotIn(forbidden, assets)
        self.assertNotRegex(self.source, r"(?m)^\s+build/?\s*$")
        self.assertIn("build/drizzli-hosted-browser-ci/report.json", self.source)
        self.assertIn("not full upstream/dependency source or runtime acceptance", self.source)

    def test_recipe_runs_after_real_build_and_before_success_export(self):
        recipe = self.source.split("- name: Prepare the successful source recipe\n", 1)[1]
        recipe = recipe.split("      - name:", 1)[0]
        self.assertIn("if: success()", recipe)
        self.assertIn("scripts/prepare_hosted_source_recipe.py --profile drizzli", recipe)
        self.assertIn('--expected-commit "$GITHUB_SHA"', recipe)
        self.assertIn('--output "$GITHUB_WORKSPACE/build/hosted-drizzli-source-recipe"', recipe)
        self.assertLess(self.source.index("python3 -B scripts/prepare_hosted_clients_ci.py"),
                        self.source.index("- name: Prepare the successful source recipe"))
        self.assertLess(self.source.index("- name: Prepare the successful source recipe"),
                        self.source.index("- name: Retain only the successful source recipe"))
        for path in ("scripts/prepare_hosted_source_recipe.py", "tests/test_hosted_source_recipe.py"):
            self.assertIn("      - " + path + "\n", self.source)
        proof = self.source.split("- name: Retain bounded build and browser diagnostics\n", 1)[1]
        proof = proof.split("      - name:", 1)[0]
        self.assertIn("if: always()", proof)
        self.assertEqual([line.strip() for line in proof.split("path: |\n", 1)[1].splitlines()
                          if line.strip()], [
            "build/hosted-client-packages.txt", "build/hosted-client-runtime/provenance.json",
            "build/hosted-clients-ci/*.json", "build/hosted-clients-ci/*.log",
            "build/drizzli-hosted-browser-ci/report.json", "build/drizzli-hosted-browser-ci/*.log",
        ])

    def test_firefox_external_libraries_are_installed_and_recorded(self):
        # The exact admitted Debian Firefox libxul has these DT_NEEDED libraries;
        # do not rely on their incidental presence in a hosted runner image.
        block = self.source.split("- name: Install dependencies only on this disposable runner\n", 1)[1]
        block = block.split("- name: Prepare authenticated public Node npm and Firefox inputs", 1)[0]
        commands = block.replace("\\\n", " ")
        install = re.search(r"apt-get install ([^\n]+)", commands).group(1)
        inventory = re.search(r"dpkg-query -W ([^\n]+)", commands).group(1)
        for package in ("libnspr4", "libevent-2.1-7t64", "libvpx9"):
            with self.subTest(package=package):
                self.assertEqual(shlex.split(install).count(package), 1)
                self.assertEqual(shlex.split(inventory).count(package), 1)
        self.assertIn("> build/hosted-client-packages.txt", inventory)

    def test_embedded_shell_syntax(self):
        blocks = re.findall(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", self.source)
        self.assertEqual(len(blocks), 11)
        for block in blocks:
            script = "\n".join(line[10:] for line in block.splitlines())
            result = subprocess.run(["bash", "-n"], input=script, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
