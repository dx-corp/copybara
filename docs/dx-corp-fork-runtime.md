# dx-corp Copybara runtime

This public fork retains the upstream Apache 2.0 source and builds the Copybara runtime from a reviewed fork commit. The official upstream weekly snapshot is not a build of this fork and is not an acceptable substitute for a pinned runtime.

`.github/workflows/source-build.yml` builds `//java/com/google/copybara:copybara_deploy.jar` with Bazel 9.2.0 and Eclipse Temurin 25.0.4+7. The workflow checks the downloaded toolchain archives by SHA-256, runs workflow and Git origin/destination tests, and executes the JAR. A successful run uploads `copybara_deploy.jar`, `copybara_deploy.jar.sha256`, and `provenance.json` for 90 days. The provenance identifies the exact fork commit, upstream base commit, build run, toolchains, and JAR digest. The build is unstamped; Copybara's `version` command reports an unknown version and epoch build timestamp. Use provenance for identity instead.

For a durable Mono runtime pin, run **Promote tested runtime** from fork `master` with the exact merged source SHA and its successful push-triggered **Fork source build** run ID. The promotion workflow verifies the run identity, downloads its three-file artifact, validates every provenance binding and checksum, and creates `runtime-<source SHA prefix>` without rebuilding the JAR. A retry accepts an existing release only when all three assets are byte-identical. Record the fork source SHA, release tag, release asset SHA-256, and successful build run in Mono's lock. A new upstream commit or toolchain change requires another reviewed fork PR, green build and tests, and a new immutable release asset. Do not follow a floating `latest` release or rebuild an older source SHA with newer tools and assume the bytes match.

`.github/actions/run-copybara` is the caller-side runtime boundary. It installs the required Java version from the action-owned `.java-version` file, downloads an explicit runtime tag, verifies the caller-supplied JAR digest, writes a short-lived GitHub App installation token to a mode-0600 temporary TOML file, and removes the file after Copybara exits. The source-build workflow resolves that same version file through `actions/setup-java` on every pull request so an unavailable vendor version cannot be promoted for callers. The token never appears in the Java command line. The caller must pin this action by commit SHA and mint an installation token limited to the authoritative source repository and one destination repository. A caller that already assembles and validates a package can pass its absolute path as `origin-folder`; Copybara binds that folder migration to the immutable `source-ref` in destination metadata.

The Copybara config remains with the authoritative source. It should read the token without embedding it:

```python
GITHUB_APP = credentials.username_password(
    credentials.static_value("x-access-token"),
    credentials.toml_key_source("github.token"),
)
```

Use `GITHUB_APP` for the GitHub origin and destination credentials. GitHub URLs using config credentials must omit the trailing `.git` (for example, `https://github.com/dx-corp/mono`) so Copybara's path-scoped credential entry matches the Git transport request. Prefer `git.github_pr_destination` with a stable generated branch, preserve destination-owned CI/policy through `destination_files`, require an immutable source SHA, and validate the prepared package before migration. To update an existing generated branch without rewriting it, the caller passes `destination-fetch` as that branch; for a new branch it passes the destination base. The action enables the fork's fail-closed fast-forward mode, which refuses any other fetch ref and emits no force refspec. For dx-corp, reuse the installed `evalops-mirror` App: it already has repository contents and pull-request permissions and is installed across the organization. Keep its private key in the authoritative caller repository; the public Copybara fork does not need or receive that key.

A caller job has this shape after a runtime release exists:

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
    with:
      fetch-depth: 0
      persist-credentials: false
  - id: app
    uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0
    with:
      app-id: ${{ secrets.PUBLIC_MIRROR_APP_ID }}
      private-key: ${{ secrets.PUBLIC_MIRROR_APP_PRIVATE_KEY }}
      owner: dx-corp
      repositories: |-
        mono
        api
      permission-contents: write
      permission-pull-requests: write
  - uses: dx-corp/copybara/.github/actions/run-copybara@<reviewed-fork-commit>
    with:
      runtime-tag: runtime-<source-sha-prefix>
      runtime-sha256: <copybara_deploy.jar sha256>
      config: config/copybara/api/copy.bara.sky
      workflow: api
      source-ref: ${{ github.sha }}
      origin-folder: ${{ runner.temp }}/verified-api-projection
      destination-fetch: sync/mono-projection
      github-token: ${{ steps.app.outputs.token }}
```

Do not enable a Copybara workflow against a destination already owned by another publisher. First prove tree equivalence against a disposable checkout, preserve the destination's existing hold/review/validation contract, then make one reviewed cutover of transport ownership.

`.github/workflows/upstream-refresh.yml` fetches `google/copybara` master weekly or on manual dispatch. It merges that revision into a new `sync/upstream-<sha>` branch and opens a PR for review. It never force-pushes, approves, or merges the PR. If the merge conflicts, the workflow fails for a human to resolve. A retry reuses an existing branch only after checking its exact upstream parent, fork parent, and marker; it can recover a failed PR creation without rewriting the branch. The only write permissions are on this trusted scheduled/manual job. The `.github/upstream-base.sha` marker records the upstream ancestor in each reviewed fork commit.

GitHub does not trigger normal `pull_request` workflows for a PR created by `GITHUB_TOKEN`. The refresh job therefore dispatches the **master-defined** source-build workflow with the proposed branch and exact head SHA, then records its run URL in the PR. That build has read-only permissions, removes checkout credentials, and refuses a branch whose remote head differs from the requested SHA. Reviewers must check that linked run succeeded for the PR head before merging. The fork repository must allow GitHub Actions to create pull requests for this automation; if its setting denies creation, the safe fallback is to open the already pushed branch's PR manually and link the dispatched run.

The fork's inherited upstream release and Docker publishing workflows are not part of this runtime path. The source-build workflow only uploads a temporary Actions artifact; release promotion is separate and manual.
