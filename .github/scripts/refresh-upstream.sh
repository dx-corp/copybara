#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_REPOSITORY:-}" != dx-corp/copybara ]]; then
  echo 'This refresh only runs for dx-corp/copybara.' >&2
  exit 1
fi
if [[ "$(git branch --show-current)" != master ]] || [[ -n "$(git status --porcelain)" ]]; then
  echo 'Refresh requires a clean fork master checkout.' >&2
  exit 1
fi

marker="$(cat .github/upstream-base.sha)"
[[ "$marker" =~ ^[0-9a-f]{40}$ ]]
git cat-file -e "${marker}^{commit}"
git merge-base --is-ancestor "$marker" HEAD

upstream_url="${COPYBARA_UPSTREAM_URL:-https://github.com/google/copybara.git}"
git fetch --no-tags "$upstream_url" master
upstream_sha="$(git rev-parse FETCH_HEAD)"
git merge-base --is-ancestor "$marker" "$upstream_sha"

if git merge-base --is-ancestor "$upstream_sha" HEAD; then
  echo "Fork already contains upstream $upstream_sha."
  exit 0
fi

branch="sync/upstream-${upstream_sha:0:12}"
base_sha="$(git rev-parse HEAD)"
if remote_branch="$(git ls-remote --exit-code --heads origin "refs/heads/$branch")"; then
  remote_branch_sha="${remote_branch%%[[:space:]]*}"
  git fetch --no-tags origin "refs/heads/$branch"
  branch_sha="$(git rev-parse FETCH_HEAD)"
  test "$branch_sha" = "$remote_branch_sha"
else
  result=$?
  [[ "$result" -eq 2 ]] || exit "$result"
  git switch -c "$branch"
  git merge --no-commit --no-ff "$upstream_sha"
  printf '%s\n' "$upstream_sha" > .github/upstream-base.sha
  git add .github/upstream-base.sha
  git commit -m "Merge google/copybara master at ${upstream_sha:0:12}"
  branch_sha="$(git rev-parse HEAD)"
  git push origin "HEAD:refs/heads/$branch"
  git switch master
fi

parents="$(git rev-list --parents -n 1 "$branch_sha")"
test "$(wc -w <<< "$parents" | tr -d ' ')" = 3
test "$(awk '{print $2}' <<< "$parents")" = "$base_sha"
test "$(awk '{print $3}' <<< "$parents")" = "$upstream_sha"
test "$(git show "$branch_sha:.github/upstream-base.sha")" = "$upstream_sha"

find_run() {
  gh run list --repo dx-corp/copybara --workflow source-build.yml \
    --event workflow_dispatch --limit 100 --json displayTitle,url |
    jq -r --arg title "Fork source build $branch_sha" \
      '[.[] | select(.displayTitle == $title)][0].url // empty'
}

run_url="$(find_run)"
if [[ -z "$run_url" ]]; then
  gh workflow run source-build.yml --repo dx-corp/copybara --ref master \
    -f "source_sha=$branch_sha" -f "branch=$branch"
  for _ in {1..30}; do
    run_url="$(find_run)"
    [[ -n "$run_url" ]] && break
    sleep 2
  done
fi
if [[ -z "$run_url" ]]; then
  echo "Build dispatch for $branch_sha was not visible; retry this workflow." >&2
  exit 1
fi

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
cat > "$body_file" <<EOF
Merge the upstream google/copybara master revision \`$upstream_sha\` into the fork.

Fork source SHA: \`$branch_sha\`
Trusted-master build for this exact SHA: $run_url

Review the successful build, migration tests, and runnable JAR for this SHA before merging. This workflow does not merge the PR or publish a runtime release.
EOF
if existing_pr="$(gh pr view "$branch" --repo dx-corp/copybara --json headRefOid,state,url 2>/dev/null)"; then
  test "$(jq -r '.headRefOid' <<< "$existing_pr")" = "$branch_sha"
  test "$(jq -r '.state' <<< "$existing_pr")" = OPEN
  jq -r '.url' <<< "$existing_pr"
else
  gh pr create --repo dx-corp/copybara --base master --head "$branch" \
    --title "Merge google/copybara at ${upstream_sha:0:12}" --body-file "$body_file"
fi
