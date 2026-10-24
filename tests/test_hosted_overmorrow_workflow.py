# SPDX-License-Identifier: GPL-3.0-only
"""Inert contracts for the explicit public Overmorrow build and export boundary."""
from pathlib import Path
import re
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / ".github/workflows/hosted-overmorrow.yml").read_text().split("\n  input-candidate:", 1)[0]


def step(name):
    return SOURCE.split("- name: " + name + "\n", 1)[1].split("      - name:", 1)[0]


def artifacts(name):
    block = step(name).split("path: |\n", 1)[1]
    return [line.strip() for line in block.splitlines() if line.strip()]


class HostedOvermorrowWorkflowTests(unittest.TestCase):
    def test_exact_sources_read_only_permissions_and_no_ambient_credentials(self):
        actions = re.findall(r"uses: ([^\s]+)", SOURCE)
        self.assertEqual(len(actions), 4)
        for action in actions:
            self.assertRegex(action, r"^[\w/-]+@[0-9a-f]{40}$")
        self.assertEqual(SOURCE.count("persist-credentials: false"), 2)
        self.assertIn("repository: VOLPAROSSA/volparossa-browser", SOURCE)
        self.assertIn("ref: 08bac388a0abfd06426bebe8f6fabd0157d2e709", SOURCE)
        self.assertIn("permissions:\n  contents: read\n", SOURCE)
        for forbidden in ("secrets.", "github.token", "contents: write", "pull_request_target"):
            self.assertNotIn(forbidden, SOURCE)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', SOURCE)
        self.assertIn('test -z "$(git status --short --untracked-files=all)"', SOURCE)

    def test_checkout_is_ignored_without_broad_new_ignore_rules(self):
        path = "build/hosted-browser-source"
        self.assertIn("path: " + path, SOURCE)
        ignored = subprocess.run(["git", "check-ignore", "--no-index", path], cwd=ROOT,
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(ignored.returncode, 0, ignored.stderr)
        self.assertEqual(ignored.stdout.strip(), path)

    def test_explicit_target_branch_and_bounded_hosted_execution(self):
        self.assertIn("workflow_dispatch:", SOURCE)
        self.assertIn("branches: [feature/hosted-overmorrow]", SOURCE)
        self.assertNotIn("schedule:", SOURCE)
        self.assertNotIn("pull_request:", SOURCE)
        self.assertIn("cancel-in-progress: false", SOURCE)
        self.assertIn("runs-on: ubuntu-24.04", SOURCE)
        self.assertIn("timeout-minutes: 45", SOURCE)
        self.assertIn('test "$RUNNER_ENVIRONMENT" = github-hosted', SOURCE)
        self.assertIn('test "$(id -u)" != 0', SOURCE)
        self.assertIn("python3 -B scripts/prepare_hosted_flutter.py --fetch", SOURCE)
        self.assertIn('"$GITHUB_WORKSPACE/build/hosted-flutter-sdk"', SOURCE)
        self.assertIn("scripts/prepare_hosted_runtime.py --with-npm --fetch", SOURCE)
        self.assertIn("python3 -B scripts/prepare_hosted_overmorrow_ci.py\n", SOURCE)
        self.assertLess(SOURCE.index("prepare_hosted_flutter.py --fetch"),
                        SOURCE.index("python3 -B scripts/prepare_hosted_overmorrow_ci.py"))
        for forbidden in ("curl |", "sysctl -w", "flutter upgrade", "sudo flutter", "npm run build"):
            self.assertNotIn(forbidden, SOURCE)

    def test_success_export_is_an_exact_source_recipe_allowlist(self):
        name = "Retain only the successful source recipe"
        self.assertIn("if: success()", step(name))
        self.assertEqual(artifacts(name), ["build/hosted-overmorrow-source-recipe"])
        self.assertIn("name: hosted-overmorrow-source-recipe-${{ github.sha }}", step(name))
        self.assertIn("include-hidden-files: true", step(name))
        self.assertEqual(SOURCE.count("include-hidden-files: true"), 1)
        for forbidden in ("overmorrow-hosted-web-ci", "firefox-hosted-ci", "hosted-client-runtime",
                          "LICENSE", "pubspec.lock", "assets-unadmitted", "**", ".git/", "profile/"):
            self.assertNotIn(forbidden, step(name))

    def test_recipe_is_bound_to_source_after_build_before_export(self):
        recipe = step("Prepare the successful source recipe")
        self.assertIn("if: success()", recipe)
        self.assertIn("scripts/prepare_hosted_source_recipe.py --profile overmorrow", recipe)
        self.assertIn('--expected-commit "$GITHUB_SHA"', recipe)
        self.assertIn('--output "$GITHUB_WORKSPACE/build/hosted-overmorrow-source-recipe"', recipe)
        self.assertLess(SOURCE.index("python3 -B scripts/prepare_hosted_overmorrow_ci.py\n"),
                        SOURCE.index("- name: Prepare the successful source recipe"))
        self.assertLess(SOURCE.index("- name: Prepare the successful source recipe"),
                        SOURCE.index("- name: Retain only the successful source recipe"))
        for path in ("scripts/prepare_hosted_source_recipe.py", "tests/test_hosted_source_recipe.py"):
            self.assertIn("      - " + path + "\n", SOURCE)

    def test_always_export_excludes_sdk_cache_profiles_and_generated_inputs(self):
        name = "Retain bounded build and browser diagnostics"
        self.assertIn("if: always()", step(name))
        self.assertEqual(artifacts(name), [
            "build/hosted-overmorrow-packages.txt",
            "build/hosted-client-runtime/provenance.json",
            "build/hosted-flutter-sdk/provenance.json",
            "build/hosted-overmorrow-ci/*.json", "build/hosted-overmorrow-ci/*.log",
            "build/overmorrow-hosted-browser-ci/report.json", "build/overmorrow-hosted-browser-ci/*.log",
            "build/overmorrow-hosted-table-ci/report.json", "build/overmorrow-hosted-table-ci/*.log",
        ])
        self.assertNotRegex(SOURCE, r"(?m)^\s+build/?\s*$")
        self.assertIn("No live Weather source request, core delivery, private bundle upload or native mobile proof.", SOURCE)
        self.assertIn("not full upstream/dependency source or runtime acceptance", SOURCE)

    def test_build_and_firefox_packages_are_installed_and_recorded(self):
        commands = step("Install dependencies only on this disposable runner").replace("\\\n", " ")
        install = shlex.split(re.search(r"apt-get install ([^\n]+)", commands).group(1))
        inventory = shlex.split(re.search(r"dpkg-query -W ([^\n]+)", commands).group(1))
        for package in ("libnspr4", "libevent-2.1-7t64", "libvpx9", "curl", "unzip", "xz-utils", "zip", "libglu1-mesa"):
            with self.subTest(package=package):
                self.assertEqual(install.count(package), 1)
                self.assertEqual(inventory.count(package), 1)
        self.assertIn("timeout 180s sudo -n", commands)
        self.assertIn("timeout 300s sudo -n", commands)

    def test_embedded_shell_and_preflight_tests(self):
        block = step("Check exact source and inert preparation contracts")
        for name in ("test_hosted_flutter.py", "test_hosted_overmorrow_ci.py", "test_hosted_overmorrow_workflow.py"):
            self.assertIn("test -f tests/" + name, block)
        self.assertIn("python3 -B -m unittest discover -s tests -p 'test_hosted_*.py'", block)
        blocks = re.findall(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", SOURCE)
        self.assertEqual(len(blocks), 7)
        for block in blocks:
            script = "\n".join(line[10:] for line in block.splitlines())
            result = subprocess.run(["bash", "-n"], input=script, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
