#!/usr/bin/env bash
set -euo pipefail

required=(
  COPYBARA_RUNTIME_TAG
  COPYBARA_RUNTIME_SHA256
  COPYBARA_CONFIG
  COPYBARA_WORKFLOW
  COPYBARA_SOURCE_REF
  COPYBARA_GITHUB_TOKEN
)
for variable_name in "${required[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required input: $variable_name" >&2
    exit 2
  fi
done

[[ "$COPYBARA_RUNTIME_TAG" =~ ^runtime-[0-9a-f]{12}$ ]] || {
  echo 'Runtime tag must be runtime- followed by 12 lowercase hexadecimal characters.' >&2
  exit 2
}
[[ "$COPYBARA_RUNTIME_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'Runtime SHA-256 must be 64 lowercase hexadecimal characters.' >&2
  exit 2
}
[[ "$COPYBARA_WORKFLOW" =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo 'Copybara workflow name contains unsafe characters.' >&2
  exit 2
}
[[ "$COPYBARA_SOURCE_REF" =~ ^[0-9a-f]{40}$ ]] || {
  echo 'Source ref must be an immutable 40-character Git SHA.' >&2
  exit 2
}
[[ "$COPYBARA_GITHUB_TOKEN" =~ ^[A-Za-z0-9_]+$ ]] || {
  echo 'GitHub App token contains unsafe characters.' >&2
  exit 2
}
if [[ "$(basename "$COPYBARA_CONFIG")" != copy.bara.sky ]] || [[ ! -f "$COPYBARA_CONFIG" ]]; then
  echo 'Copybara config must be an existing file named copy.bara.sky.' >&2
  exit 2
fi

echo "::add-mask::$COPYBARA_GITHUB_TOKEN"
runtime_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/copybara-runtime.XXXXXX")"
cleanup() {
  rm -f "$runtime_dir/credentials.toml"
  rm -rf "$runtime_dir"
}
trap cleanup EXIT

jar="$runtime_dir/copybara_deploy.jar"
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 --silent --show-error \
  --output "$jar" \
  "https://github.com/dx-corp/copybara/releases/download/${COPYBARA_RUNTIME_TAG}/copybara_deploy.jar"
printf '%s  %s\n' "$COPYBARA_RUNTIME_SHA256" "$jar" | shasum -a 256 --check --status

credential_file="$runtime_dir/credentials.toml"
umask 077
printf '[github]\ntoken = "%s"\n' "$COPYBARA_GITHUB_TOKEN" > "$credential_file"
credential_mode="$(python3 -c 'import os, stat, sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])' "$credential_file")"
test "$credential_mode" = 600

GIT_TERMINAL_PROMPT=0 java -jar "$jar" migrate \
  --credential-file "$credential_file" \
  --use-credentials-from-config=true \
  --github-api-bearer-auth=true \
  --validate-starlark=STRICT \
  "$COPYBARA_CONFIG" "$COPYBARA_WORKFLOW" "$COPYBARA_SOURCE_REF"
