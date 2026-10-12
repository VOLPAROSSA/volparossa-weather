# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import re
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/hosted-android.yml").read_text()

    def test_explicit_candidate_only_and_source_actions_pinned(self):
        self.assertIn("workflow_dispatch:", self.text)
        trigger = self.text.split("  push:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("branches: [feature/overmorrow-native-android]", trigger)
        self.assertIn("    paths:\n", trigger)
        self.assertIn("tests/fixtures/hosted-android-repositories/*", trigger)
        self.assertIn("tests/fixtures/hosted-android-repositories/compiler-property/*.gradle", trigger)
        self.assertIn("      - third_party/android-emulator-local-package.xml\n", trigger)
        self.assertTrue((ROOT / "third_party/android-emulator-local-package.xml").is_file())
        self.assertNotIn("main", trigger)
        self.assertNotIn("**", trigger)
        self.assertNotIn("README", trigger)
        self.assertNotIn("  pull_request:", self.text)
        self.assertNotIn("  schedule:", self.text)
        for action in re.findall(r"uses: (\S+)", self.text):
            self.assertRegex(action, r"@[0-9a-f]{40}$")
        self.assertIn('git rev-parse HEAD', self.text)
        self.assertIn('persist-credentials: false', self.text)

    def test_workflow_commands_parse_and_python_entrypoints_exist(self):
        blocks = re.findall(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", self.text)
        self.assertEqual(len(blocks), 7)
        for block in blocks:
            result = subprocess.run(["bash", "-n"], input=textwrap.dedent(block),
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
        scripts = re.findall(r"python3 -B ([a-z][a-zA-Z0-9_./-]+\.py)", self.text)
        self.assertEqual(len(scripts), 5)
        for name in scripts:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_actual_emulator_not_apk_only(self):
        self.assertIn("scripts/prepare_hosted_android_ci.py", self.text)
        self.assertIn("emulator-cleanup.json", self.text)
        self.assertIn("overmorrow-hosted-android-proof/report.json", self.text)
        self.assertIn("hosted-android-debug-unadmitted-", self.text)

    def test_bounded_disposable_prerequisites_and_acl_restore(self):
        self.assertIn("runs-on: ubuntu-24.04", self.text)
        self.assertIn("timeout-minutes: 75", self.text)
        self.assertIn('test "$RUNNER_ENVIRONMENT" = github-hosted', self.text)
        self.assertIn("openjdk-17-jdk-headless", self.text)
        self.assertIn("setfacl --restore=build/hosted-android-kvm.acl", self.text)
        self.assertNotIn("chmod 666", self.text)
        self.assertNotIn("usermod", self.text)
        self.assertNotIn("sysctl", self.text)

    def test_no_private_runtime_uploads(self):
        self.assertIn("            build/hosted-android-inputs/download-failure.json\n", self.text)
        self.assertEqual(self.text.count("            build/overmorrow-hosted-android-proof/emulator-diagnostic.json\n"), 1)
        self.assertNotIn("emulator-diagnostic.part", self.text)
        self.assertEqual(self.text.count("            build/overmorrow-hosted-android-proof/guest-network-diagnostic.json\n"), 1)
        self.assertNotIn("guest-network-diagnostic.part", self.text)
        for name in ("inputs", "diagnostic", "cleanup"):
            self.assertEqual(self.text.count("            build/overmorrow-hosted-android-proof/emulator-preflight-" + name + ".json\n"), 1)
        self.assertNotIn("emulator-preflight-diagnostic.part", self.text)
        paths = []
        for block in self.text.split("          path: |\n")[1:]:
            for line in block.splitlines():
                if not line.startswith("            "):
                    break
                paths.append(line.strip())
        self.assertGreater(len(paths), 10)
        for value in paths:
            self.assertNotRegex(value, r"(private|\.git|\.gradle|avd|keystore|token|android-inputs/sdk)")
            self.assertNotIn("**", value)

    def test_canonical_awk_package_is_declared_and_recorded_only_on_disposable_runner(self):
        install = self.text.split("apt-get install --yes --no-install-recommends", 1)[1].split("umask 077", 1)[0]
        inventory = self.text.split("dpkg-query -W", 1)[1].split("> build/hosted-android-packages.txt", 1)[0]
        self.assertEqual(install.split().count("mawk"), 1)
        self.assertEqual(inventory.split().count("mawk"), 1)
        self.assertNotIn("update-alternatives", self.text)
        self.assertNotIn("/etc/alternatives", self.text)


if __name__ == "__main__":
    unittest.main()
