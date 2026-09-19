#!/usr/bin/env python3
"""Fail-closed verification for a dx-corp Copybara runtime artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_FILES = {
    "copybara_deploy.jar",
    "copybara_deploy.jar.sha256",
    "provenance.json",
}
EXPECTED_PROVENANCE_KEYS = {
    "bazel_version",
    "github_run_attempt",
    "github_run_id",
    "jar_sha256",
    "jdk_distribution",
    "jdk_version",
    "repository",
    "schema",
    "source_sha",
    "target",
    "upstream_base_sha",
}
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--repository", default="dx-corp/copybara")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(
    artifact_dir: Path,
    *,
    source_sha: str,
    run_id: str,
    run_attempt: str,
    repository: str,
) -> dict[str, str]:
    if not GIT_SHA_RE.fullmatch(source_sha):
        raise ValueError("source SHA must be 40 lowercase hexadecimal characters")
    if not run_id.isascii() or not run_id.isdigit() or run_id.startswith("0"):
        raise ValueError("run ID must be a positive decimal integer")
    if (
        not run_attempt.isascii()
        or not run_attempt.isdigit()
        or run_attempt.startswith("0")
    ):
        raise ValueError("run attempt must be a positive decimal integer")
    if not artifact_dir.is_dir() or artifact_dir.is_symlink():
        raise ValueError("artifact directory is missing or unsafe")

    entries = {entry.name for entry in artifact_dir.iterdir()}
    if entries != EXPECTED_FILES:
        raise ValueError(
            f"artifact files mismatch: expected {sorted(EXPECTED_FILES)}, got {sorted(entries)}"
        )
    for name in EXPECTED_FILES:
        artifact = artifact_dir / name
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError(f"artifact file is missing or unsafe: {name}")

    checksum_text = (artifact_dir / "copybara_deploy.jar.sha256").read_text(
        encoding="utf-8"
    )
    checksum_match = re.fullmatch(
        r"([0-9a-f]{64})  copybara_deploy\.jar\n", checksum_text
    )
    if checksum_match is None:
        raise ValueError("checksum file has an unexpected format")

    jar_digest = sha256(artifact_dir / "copybara_deploy.jar")
    if checksum_match.group(1) != jar_digest:
        raise ValueError("JAR digest does not match checksum file")

    provenance = json.loads(
        (artifact_dir / "provenance.json").read_text(encoding="utf-8")
    )
    if not isinstance(provenance, dict) or set(provenance) != EXPECTED_PROVENANCE_KEYS:
        raise ValueError("provenance fields do not match the runtime-v1 schema")
    expected = {
        "schema": "dx-corp.copybara-runtime-v1",
        "repository": repository,
        "source_sha": source_sha,
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        "jar_sha256": jar_digest,
        "target": "//java/com/google/copybara:copybara_deploy.jar",
        "bazel_version": "9.2.0",
        "jdk_distribution": "Eclipse Temurin",
        "jdk_version": "25.0.4+7",
    }
    for key, value in expected.items():
        if provenance.get(key) != value:
            raise ValueError(f"provenance mismatch for {key}")
    if not GIT_SHA_RE.fullmatch(provenance.get("upstream_base_sha", "")):
        raise ValueError("provenance has an invalid upstream base SHA")
    return {
        "jar_sha256": jar_digest,
        "source_sha": source_sha,
        "upstream_base_sha": provenance["upstream_base_sha"],
    }


def main() -> None:
    args = parse_args()
    result = verify(
        args.artifact_dir,
        source_sha=args.source_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        repository=args.repository,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
