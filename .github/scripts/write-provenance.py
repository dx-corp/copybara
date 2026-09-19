#!/usr/bin/env python3
"""Write source-bound metadata for a Copybara Actions build artifact."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: write-provenance.py ARTIFACT_DIR")
    artifact_dir = Path(sys.argv[1])
    jar = artifact_dir / "copybara_deploy.jar"
    source_sha = git("rev-parse", "HEAD")
    upstream_sha = Path(".github/upstream-base.sha").read_text().strip()
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (source_sha, upstream_sha)):
        raise SystemExit("invalid source or upstream SHA")
    if subprocess.run(["git", "merge-base", "--is-ancestor", upstream_sha, source_sha]).returncode:
        raise SystemExit("upstream SHA is not in source history")
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    expected = (artifact_dir / "copybara_deploy.jar.sha256").read_text().strip()
    if expected != f"{digest}  copybara_deploy.jar":
        raise SystemExit("checksum sidecar differs from JAR")
    provenance = {
        "schema": "dx-corp.copybara-runtime-v1",
        "repository": os.environ.get("GITHUB_REPOSITORY", "dx-corp/copybara"),
        "source_sha": source_sha,
        "upstream_base_sha": upstream_sha,
        "bazel_version": "9.2.0",
        "jdk_distribution": "Eclipse Temurin",
        "jdk_version": "25.0.4+7",
        "target": "//java/com/google/copybara:copybara_deploy.jar",
        "jar_sha256": digest,
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    }
    (artifact_dir / "provenance.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
