#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?Missing runner temp directory}"
: "${GITHUB_OUTPUT:?Missing action output file}"
action_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
manifest="$action_dir/../../../native/prepared-tree/Cargo.toml"
target="$(mktemp -d "$RUNNER_TEMP/copybara-native.XXXXXX")"
# The caller installs Rust using its existing pinned toolchain. --offline and
# --locked prohibit dependency resolution/downloads; this crate has no deps.
rustc --version
cargo build --offline --locked --release --manifest-path "$manifest" --target-dir "$target"
binary="$target/release/copybara-prepared-tree"
test -x "$binary"
digest="$(shasum -a 256 "$binary" | awk '{print $1}')"
[[ "$digest" =~ ^[0-9a-f]{64}$ ]]
printf 'binary=%s\nsha256=%s\n' "$binary" "$digest" >> "$GITHUB_OUTPUT"
# The binary must survive until later caller steps. Actions owns RUNNER_TEMP
# cleanup at the job boundary; this action never modifies the caller checkout.
