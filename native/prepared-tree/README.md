# Native prepared-tree assembly (experimental)

This is the first bounded Rust replacement for the **local tree-assembly** part
of Copybara's `folder.origin` → Git destination path. It is not a replacement for
Copybara's Starlark engine or GitHub publisher. Production still uses the pinned
Java release; this binary is not wired into the publishing action.

The reason to extract this piece: Mono already prepares and validates standalone
packages, supplies explicit origin files, and uses no Copybara transformations.
That path can construct an identical Git tree without downloading a JAR or
starting a JVM. The implementation has no Cargo dependencies and uses existing
Git plumbing. It does not duplicate Mono's projection policies.

## Contract

```sh
copybara-prepared-tree DESTINATION PREPARED BASE_SHA MANAGED_NUL ORIGIN_NUL
```

- `DESTINATION`: trusted complete local Git repository.
- `PREPARED`: immutable local directory containing already-validated bytes.
- `BASE_SHA`: full lowercase commit ID, not a branch, expression, or tree ID.
- `MANAGED_NUL`: NUL-terminated inventory of **every old managed file and every
  incoming file**, expanded by the authoritative caller (not glob patterns).
- `ORIGIN_NUL`: NUL-terminated inventory of incoming files; must be a nonempty
  subset of the managed inventory.

The command prints one tree ID. Old managed files omitted from origin are
deleted; destination-owned entries are preserved. It writes only Git objects,
using a private temporary index removed on exit. It never writes the real
worktree/index, creates commits, updates refs, pushes, reads credentials, or
calls GitHub. Interrupted execution can leave a small temp directory; newly
written unreachable objects are handled by normal Git garbage collection.

Paths must be normalized relative UTF-8 paths; duplicate, traversal, `.git`,
Windows-style, and trailing-dot/space components are rejected. All source path
components must be real directories/files, never symlinks. File/directory
collisions with retained destination files fail closed. Only Unix platforms are
supported. Executable bits and raw file bytes are preserved, independently of
`.gitignore` and Git clean/EOL filters.

This helper is **not an authorization boundary**. The caller must authorize the
inventories and freeze the prepared directory. It does not protect against a
concurrently malicious process changing inputs. It does not read source policy,
decide publication eligibility, infer stale files, or handle synchronization
holds. Git attributes transformations are intentionally not implemented.

## Verification

```sh
rustup run 1.93.0 cargo test --locked --manifest-path native/prepared-tree/Cargo.toml
rustup run 1.93.0 cargo clippy --locked --manifest-path native/prepared-tree/Cargo.toml --all-targets -- -D warnings
rustup run 1.93.0 cargo build --locked --release --manifest-path native/prepared-tree/Cargo.toml
python3 native/prepared-tree/parity.py \
  --jar /absolute/path/to/copybara_deploy.jar \
  --native native/prepared-tree/target/release/copybara-prepared-tree
```

The differential test compares actual Git tree IDs with the Java engine across
306 incoming files, stale deletions, destination-owned workflow preservation,
binary content, ignored HTML, spaces, and executable bits. Repeated runs must
produce the same tree. All Git publication in the test is to disposable local
repositories; Java cache/output is contained in the fixture temp directory.
CI runs this test against the JAR built from the same source revision.

Initial local measurement (ARM64 macOS, native ARM64 Temurin 25, Rust 1.93.0,
three runs, pinned production JAR SHA-256
`7a3e15f86f0f43258cab806a96f7a2cc4fb0d46c7329016d42c828e704a45f07`):

| Measurement | Native | Java |
| --- | ---: | ---: |
| Median local operation | 0.774 s | 6.914 s |
| Artifact size | 421,360 bytes | 14,091,857 bytes (JAR only) |

Both produced tree `de0e3aeb717e4b5c6ee8b1dd254fedab0f90a2ec`.
This is a small synthetic fixture, not an end-to-end speedup claim: Java also
creates a commit and updates a local ref; native only constructs the tree.
Network, App authentication, toolchain installation, and CI queue time are
excluded. CI timings are informational, not a flaky performance gate.

## Before a production switch

Keep the existing Java path as the default until native/Java tree parity has
been established on each real catalog projection, including replay and stale
deletion. Preserve Mono's existing authorization, ownership, provenance,
validation and App-token publication boundaries. Evaluate destination Git
attributes/filters explicitly. A future caller must reject any mismatch before
publication; do not silently fall back and call that a successful native run.
No binary release, publisher cutover, or whole-engine rewrite is included here.
