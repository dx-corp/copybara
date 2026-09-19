#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("run-github-app-migration.sh")


class RunGithubAppMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.jar = self.root / "source.jar"
        self.jar.write_bytes(b"copybara runtime")
        self.config = self.root / "copy.bara.sky"
        self.config.write_text("# fixture\n", encoding="utf-8")
        self.capture = self.root / "java-args"
        curl = self.bin / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "while (($#)); do\n"
            "  if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi\n"
            "done\n"
            'cp "$FAKE_JAR" "$output"\n',
            encoding="utf-8",
        )
        java = self.bin / "java"
        java.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'test "${GIT_TERMINAL_PROMPT:-}" = 0\n'
            'printf \'%s\\n\' "$@" > "$FAKE_CAPTURE"\n'
            "credential=''\n"
            "for ((i=1; i<=$#; i++)); do\n"
            "  if [[ ${!i} == --credential-file ]]; then next=$((i+1)); credential=${!next}; fi\n"
            "done\n"
            "mode=$(python3 -c 'import os, stat, sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])' \"$credential\")\n"
            'test "$mode" = 600\n'
            'grep -q \'token = "ghs_fixture"\' "$credential"\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)
        java.chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.bin}:{env['PATH']}",
                "RUNNER_TEMP": str(self.root),
                "FAKE_JAR": str(self.jar),
                "FAKE_CAPTURE": str(self.capture),
                "COPYBARA_RUNTIME_TAG": "runtime-123456789abc",
                "COPYBARA_RUNTIME_SHA256": hashlib.sha256(
                    self.jar.read_bytes()
                ).hexdigest(),
                "COPYBARA_CONFIG": str(self.config),
                "COPYBARA_WORKFLOW": "api",
                "COPYBARA_SOURCE_REF": "a" * 40,
                "COPYBARA_GITHUB_TOKEN": "ghs_fixture",
            }
        )
        return env

    def test_invokes_java_without_token_in_arguments(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ghs_fixture", self.capture.read_text(encoding="utf-8"))
        self.assertIn(
            "--github-api-bearer-auth", self.capture.read_text(encoding="utf-8")
        )
        self.assertIn(
            "--validate-starlark=STRICT", self.capture.read_text(encoding="utf-8")
        )
        self.assertIn("::add-mask::ghs_fixture", result.stdout)
        self.assertFalse(any(self.root.glob("copybara-runtime.*")))

    def test_rejects_digest_mismatch_before_java(self) -> None:
        env = self.environment()
        env["COPYBARA_RUNTIME_SHA256"] = "0" * 64
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
