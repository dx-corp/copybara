#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify-runtime-artifact.py")
SPEC = importlib.util.spec_from_file_location("verify_runtime_artifact", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE_SHA = "1" * 40
UPSTREAM_SHA = "2" * 40
RUN_ID = "12345"
RUN_ATTEMPT = "1"


class VerifyRuntimeArtifactTest(unittest.TestCase):
    def make_artifact(self, root: Path) -> str:
        jar = root / "copybara_deploy.jar"
        jar.write_bytes(b"tested copybara jar\n")
        digest = hashlib.sha256(jar.read_bytes()).hexdigest()
        (root / "copybara_deploy.jar.sha256").write_text(
            f"{digest}  copybara_deploy.jar\n", encoding="utf-8"
        )
        (root / "provenance.json").write_text(
            json.dumps(
                {
                    "bazel_version": "9.2.0",
                    "github_run_attempt": RUN_ATTEMPT,
                    "github_run_id": RUN_ID,
                    "jar_sha256": digest,
                    "jdk_distribution": "Eclipse Temurin",
                    "jdk_version": "25.0.4+7",
                    "repository": "dx-corp/copybara",
                    "schema": "dx-corp.copybara-runtime-v1",
                    "source_sha": SOURCE_SHA,
                    "target": "//java/com/google/copybara:copybara_deploy.jar",
                    "upstream_base_sha": UPSTREAM_SHA,
                }
            ),
            encoding="utf-8",
        )
        return digest

    def test_accepts_exact_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            digest = self.make_artifact(root)
            self.assertEqual(
                MODULE.verify(
                    root,
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    run_attempt=RUN_ATTEMPT,
                    repository="dx-corp/copybara",
                ),
                {
                    "jar_sha256": digest,
                    "source_sha": SOURCE_SHA,
                    "upstream_base_sha": UPSTREAM_SHA,
                },
            )

    def test_rejects_modified_jar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            (root / "copybara_deploy.jar").write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "does not match"):
                MODULE.verify(
                    root,
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    run_attempt=RUN_ATTEMPT,
                    repository="dx-corp/copybara",
                )

    def test_rejects_wrong_source_run_or_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            for kwargs, field in [
                (
                    {
                        "source_sha": "3" * 40,
                        "run_id": RUN_ID,
                        "run_attempt": RUN_ATTEMPT,
                        "repository": "dx-corp/copybara",
                    },
                    "source_sha",
                ),
                (
                    {
                        "source_sha": SOURCE_SHA,
                        "run_id": "999",
                        "run_attempt": RUN_ATTEMPT,
                        "repository": "dx-corp/copybara",
                    },
                    "github_run_id",
                ),
                (
                    {
                        "source_sha": SOURCE_SHA,
                        "run_id": RUN_ID,
                        "run_attempt": "2",
                        "repository": "dx-corp/copybara",
                    },
                    "github_run_attempt",
                ),
                (
                    {
                        "source_sha": SOURCE_SHA,
                        "run_id": RUN_ID,
                        "run_attempt": RUN_ATTEMPT,
                        "repository": "other/repo",
                    },
                    "repository",
                ),
            ]:
                with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, field
                ):
                    MODULE.verify(root, **kwargs)

    def test_rejects_extra_or_symlinked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            (root / "unexpected").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "files mismatch"):
                MODULE.verify(
                    root,
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    run_attempt=RUN_ATTEMPT,
                    repository="dx-corp/copybara",
                )
            (root / "unexpected").unlink()
            (root / "copybara_deploy.jar.sha256").unlink()
            (root / "copybara_deploy.jar.sha256").symlink_to("copybara_deploy.jar")
            with self.assertRaisesRegex(ValueError, "missing or unsafe"):
                MODULE.verify(
                    root,
                    source_sha=SOURCE_SHA,
                    run_id=RUN_ID,
                    run_attempt=RUN_ATTEMPT,
                    repository="dx-corp/copybara",
                )


if __name__ == "__main__":
    unittest.main()
