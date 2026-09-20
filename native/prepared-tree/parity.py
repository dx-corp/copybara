#!/usr/bin/env python3
"""Offline Java/native tree parity and startup-inclusive timings; no GitHub writes."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout.decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--java", default="java")
    parser.add_argument("--runs", default=3, type=int)
    parser.add_argument("--files", default=300, type=int)
    args = parser.parse_args()
    if args.runs < 1 or args.files < 1:
        parser.error("runs and files must be positive")
    jar, native = args.jar.resolve(), args.native.resolve()
    with tempfile.TemporaryDirectory(prefix="copybara-parity-") as tmp:
        root = Path(tmp).resolve()
        repo, prepared = root / "destination", root / "prepared"
        repo.mkdir()
        prepared.mkdir()
        run("git", "init", "-q", "-b", "main", str(repo))
        run("git", "config", "user.name", "Parity Test", cwd=repo)
        run("git", "config", "user.email", "parity@example.invalid", cwd=repo)
        for name, content in {".github/workflows/owned.yml": b"destination-owned\n",
                              ".gitignore": b"*.html\n", "stale.txt": b"delete me\n",
                              "nested/old.txt": b"delete nested\n"}.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "baseline", cwd=repo)
        base = run("git", "rev-parse", "HEAD", cwd=repo)
        payloads = {f"package/file-{i:05}.txt": (f"package content {i}\n" * 32).encode()
                    for i in range(args.files)}
        payloads.update({"review.html": b"<h1>embedded template</h1>\n",
                         "bin/run": b"#!/bin/sh\nexit 0\n", "binary": bytes(range(256)),
                         "space name": b"space\n", "nested/new.txt": b"replacement\n",
                         ".repository-projection.json": b'{"sourceSha":"' + b"1" * 40 + b'"}\n'})
        for name, content in payloads.items():
            path = prepared / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (prepared / "bin/run").chmod(0o755)
        origin = sorted(payloads)
        managed = sorted(origin + ["stale.txt", "nested/old.txt"])
        for name, paths in [("origin.nul", origin), ("managed.nul", managed)]:
            (root / name).write_bytes(b"".join(p.encode() + b"\0" for p in paths))
        config = root / "copy.bara.sky"
        config_text = f'''core.workflow(
    name = "parity",
    origin = folder.origin(inside_symlinks_mode = "FAIL", outside_symlinks_mode = "FAIL", broken_symlinks_mode = "FAIL"),
    destination = git.destination(url = {json.dumps(repo.as_uri())}, fetch = "main", push = "java-output"),
    authoring = authoring.overwrite("Parity Test <parity@example.invalid>"),
    mode = "SQUASH",
    ask_for_confirmation = False,
    origin_files = glob({json.dumps(origin)}),
    destination_files = glob({json.dumps(managed)}),
    transformations = [],
)
'''
        native_times, java_times = [], []
        tree = None
        index_before = (repo / ".git/index").read_bytes()
        for iteration in range(args.runs):
            branch = f"java-output-{iteration}"
            config.write_text(config_text.replace('push = "java-output"', f'push = "{branch}"'))
            started = time.monotonic()
            native_tree = run(str(native), str(repo), str(prepared), base,
                              str(root / "managed.nul"), str(root / "origin.nul"))
            native_times.append(time.monotonic() - started)
            assert (repo / ".git/index").read_bytes() == index_before
            started = time.monotonic()
            run(args.java, "-jar", str(jar), "migrate", "--force", f"--output-root={root / 'java-cache'}",
                "--git-committer-name=Parity Test", "--git-committer-email=parity@example.invalid",
                str(config), "parity", str(prepared))
            java_times.append(time.monotonic() - started)
            java_tree = run("git", "rev-parse", branch + "^{tree}", cwd=repo)
            if native_tree != java_tree:
                diff = run("git", "diff", "--stat", native_tree, java_tree, cwd=repo)
                raise AssertionError(f"tree mismatch: native={native_tree} java={java_tree}\n{diff}")
            assert tree is None or tree == native_tree
            tree = native_tree
            assert run("git", "status", "--porcelain", cwd=repo) == ""
            assert run("git", "rev-parse", "HEAD", cwd=repo) == base
            assert (repo / ".github/workflows/owned.yml").read_bytes() == b"destination-owned\n"
        print(json.dumps({
            "tree": tree, "files": len(origin), "runs": args.runs,
            "jarSha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
            "nativeBytes": native.stat().st_size,
            "nativeSeconds": native_times, "javaSeconds": java_times,
            "nativeMedianSeconds": statistics.median(native_times),
            "javaMedianSeconds": statistics.median(java_times),
            "scope": "local prepared-tree assembly; Java also creates a commit and local ref; excludes network/auth/CI queue",
        }, indent=2))


if __name__ == "__main__":
    main()
