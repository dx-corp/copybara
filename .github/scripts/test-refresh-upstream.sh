#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
git -c init.defaultBranch=master init -q --bare "$scratch/upstream.git"
git -c init.defaultBranch=master init -q --bare "$scratch/origin.git"
git -c init.defaultBranch=master init -q "$scratch/upstream-work"
(
  cd "$scratch/upstream-work"
  git config user.name 'Fixture'
  git config user.email 'fixture@example.com'
  printf 'base\n' > upstream.txt
  git add upstream.txt
  git commit -qm 'Upstream base'
  git remote add origin "$scratch/upstream.git"
  git push -q origin master
)
base_sha="$(git -C "$scratch/upstream-work" rev-parse HEAD)"
git clone -q "$scratch/upstream.git" "$scratch/fork"
(
  cd "$scratch/fork"
  git config user.name 'Fixture'
  git config user.email 'fixture@example.com'
  git remote set-url origin "$scratch/origin.git"
  mkdir -p .github
  printf '%s\n' "$base_sha" > .github/upstream-base.sha
  git add .github/upstream-base.sha
  git commit -qm 'Fork metadata'
  git push -q origin master
)
(
  cd "$scratch/upstream-work"
  printf 'new\n' >> upstream.txt
  git commit -qam 'Upstream change'
  git push -q origin master
)
upstream_sha="$(git -C "$scratch/upstream-work" rev-parse HEAD)"
mkdir "$scratch/bin"
cat > "$scratch/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$GH_STATE_DIR/calls"
case "$1 $2" in
  'run list')
    if [[ -f "$GH_STATE_DIR/run-sha" ]]; then
      printf '[{"displayTitle":"Fork source build %s","url":"https://github.com/dx-corp/copybara/actions/runs/1"}]\n' "$(cat "$GH_STATE_DIR/run-sha")"
    else
      printf '[]\n'
    fi
    ;;
  'workflow run')
    for arg in "$@"; do
      if [[ "$arg" == source_sha=* ]]; then
        printf '%s\n' "${arg#source_sha=}" > "$GH_STATE_DIR/run-sha"
      fi
    done
    ;;
  'pr view')
    [[ -f "$GH_STATE_DIR/pr-created" ]] || exit 1
    printf '{"headRefOid":"%s","state":"OPEN","url":"https://github.com/dx-corp/copybara/pull/1"}\n' "$(cat "$GH_STATE_DIR/run-sha")"
    ;;
  'pr create')
    if [[ ! -f "$GH_STATE_DIR/pr-failed-once" ]]; then
      touch "$GH_STATE_DIR/pr-failed-once"
      exit 1
    fi
    touch "$GH_STATE_DIR/pr-created"
    printf 'https://github.com/dx-corp/copybara/pull/1\n'
    ;;
  *) exit 1 ;;
esac
EOF
chmod 755 "$scratch/bin/gh"
if (
  cd "$scratch/fork"
  GITHUB_REPOSITORY=dx-corp/copybara \
    COPYBARA_UPSTREAM_URL="$scratch/upstream.git" \
    GH_STATE_DIR="$scratch" PATH="$scratch/bin:$PATH" \
    bash "$script_dir/refresh-upstream.sh" > "$scratch/first.log" 2>&1
); then
  echo 'Fixture did not simulate the first PR creation failure.' >&2
  exit 1
fi
branch="sync/upstream-${upstream_sha:0:12}"
branch_sha="$(git --git-dir="$scratch/origin.git" rev-parse "refs/heads/$branch")"
test "$(git --git-dir="$scratch/origin.git" show "$branch_sha:.github/upstream-base.sha")" = "$upstream_sha"
test "$(git --git-dir="$scratch/origin.git" rev-list --parents -n 1 "$branch_sha" | wc -w | tr -d ' ')" = 3
git --git-dir="$scratch/origin.git" merge-base --is-ancestor "$upstream_sha" "$branch_sha"
test "$(cat "$scratch/run-sha")" = "$branch_sha"
test ! -f "$scratch/pr-created"

# Retrying the same upstream revision reuses the verified branch and recovers the PR.
(
  cd "$scratch/fork"
  GITHUB_REPOSITORY=dx-corp/copybara \
    COPYBARA_UPSTREAM_URL="$scratch/upstream.git" \
    GH_STATE_DIR="$scratch" PATH="$scratch/bin:$PATH" \
    bash "$script_dir/refresh-upstream.sh" > "$scratch/retry.log" 2>&1
)
test -f "$scratch/pr-created"
test "$(git --git-dir="$scratch/origin.git" rev-parse "refs/heads/$branch")" = "$branch_sha"
test "$(grep -c '^workflow run ' "$scratch/calls")" = 1
test "$(grep -c '^pr create ' "$scratch/calls")" = 2
grep -F "pr create --repo dx-corp/copybara --base master --head $branch" "$scratch/calls" > /dev/null
echo 'Upstream refresh fixture passed.'
