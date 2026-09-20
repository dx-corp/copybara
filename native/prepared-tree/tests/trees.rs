use copybara_prepared_tree::build_tree;
use std::{
    fs,
    os::unix::fs::{PermissionsExt, symlink},
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture {
    root: PathBuf,
    repo: PathBuf,
    prepared: PathBuf,
    base: String,
}
fn git(repo: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_string()
}
fn write(root: &Path, name: &str, content: &[u8]) {
    let path = root.join(name);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}
fn nul(paths: &[&str]) -> Vec<u8> {
    paths.iter().flat_map(|p| p.bytes().chain([0])).collect()
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "native-tree-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let repo = root.join("repo");
        let prepared = root.join("prepared");
        fs::create_dir(&repo).unwrap();
        fs::create_dir(&prepared).unwrap();
        git(&repo, &["init", "-q"]);
        git(&repo, &["config", "user.name", "Tree Test"]);
        git(&repo, &["config", "user.email", "tree@example.invalid"]);
        write(&repo, ".github/workflows/owned.yml", b"keep\n");
        write(&repo, "stale.txt", b"remove\n");
        write(&repo, ".gitignore", b"*.html\n");
        git(&repo, &["add", "."]);
        git(&repo, &["commit", "-qm", "base"]);
        let base = git(&repo, &["rev-parse", "HEAD"]);
        Self {
            root,
            repo,
            prepared,
            base,
        }
    }
    fn build(
        &self,
        managed: &[&str],
        origin: &[&str],
    ) -> Result<String, Box<dyn std::error::Error>> {
        build_tree(
            &self.repo,
            &self.prepared,
            &self.base,
            &nul(managed),
            &nul(origin),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}

#[test]
fn tree_matches_git_with_deletion_ignored_binary_and_executable_files() {
    let f = Fixture::new();
    write(&f.prepared, "review.html", b"<h1>retained</h1>\n");
    write(&f.prepared, "bin/run", b"#!/bin/sh\nexit 0\n");
    fs::set_permissions(
        f.prepared.join("bin/run"),
        fs::Permissions::from_mode(0o755),
    )
    .unwrap();
    write(&f.prepared, "binary", &[0, 255, 1, 13, 10]);
    let paths = ["review.html", "bin/run", "binary"];
    let actual = f
        .build(&["stale.txt", "review.html", "bin/run", "binary"], &paths)
        .unwrap();
    // Native assembly left the real worktree and index untouched.
    assert_eq!(git(&f.repo, &["status", "--porcelain"]), "");
    assert_eq!(git(&f.repo, &["rev-parse", "HEAD"]), f.base);
    assert!(f.repo.join("stale.txt").exists());
    fs::remove_file(f.repo.join("stale.txt")).unwrap();
    for path in paths {
        write(&f.repo, path, &fs::read(f.prepared.join(path)).unwrap());
    }
    fs::set_permissions(f.repo.join("bin/run"), fs::Permissions::from_mode(0o755)).unwrap();
    git(&f.repo, &["add", "-Af", "."]);
    assert_eq!(actual, git(&f.repo, &["write-tree"]));
}

#[test]
fn preserves_dirty_worktree_and_index_and_uses_exact_base() {
    let f = Fixture::new();
    write(&f.repo, "staged", b"unrelated staged edit");
    git(&f.repo, &["add", "staged"]);
    write(&f.repo, "stale.txt", b"unrelated unstaged edit");
    let before = fs::read(f.repo.join(".git/index")).unwrap();
    let status = git(&f.repo, &["status", "--porcelain"]);
    write(&f.prepared, "new", b"content");
    let tree = f.build(&["new"], &["new"]).unwrap();
    assert_eq!(before, fs::read(f.repo.join(".git/index")).unwrap());
    assert_eq!(status, git(&f.repo, &["status", "--porcelain"]));
    assert!(!git(&f.repo, &["ls-tree", "-r", "--name-only", &tree]).contains("staged"));
}

#[test]
fn unusual_names_round_trip_and_replay_is_identical() {
    let f = Fixture::new();
    let names = [
        "space name",
        "tab\tname",
        "line\nbreak",
        "quote\"name",
        "café",
        "-option",
    ];
    for name in names {
        write(&f.prepared, name, name.as_bytes());
    }
    let a = f.build(&names, &names).unwrap();
    assert_eq!(a, f.build(&names, &names).unwrap());
    for name in names {
        write(&f.repo, name, name.as_bytes());
    }
    git(&f.repo, &["add", "-A"]);
    assert_eq!(a, git(&f.repo, &["write-tree"]));
}

#[test]
fn rejects_invalid_manifests_and_non_commit_base() {
    let f = Fixture::new();
    write(&f.prepared, "ok", b"ok");
    for name in [
        "",
        "../escape",
        "/absolute",
        "a/../b",
        "a//b",
        "./ok",
        ".git/config",
        ".GIT/config",
        "a\\b",
        "x:y",
        "trailing.",
    ] {
        assert!(f.build(&[name], &[name]).is_err(), "{name:?}");
    }
    assert!(f.build(&["ok", "ok"], &["ok"]).is_err());
    assert!(f.build(&["other"], &["ok"]).is_err());
    assert!(f.build(&["ok"], &[]).is_err());
    assert!(build_tree(&f.repo, &f.prepared, &f.base, b"ok", b"ok\0").is_err());
    assert!(build_tree(&f.repo, &f.prepared, "HEAD", b"ok\0", b"ok\0").is_err());
    let tree = git(&f.repo, &["rev-parse", "HEAD^{tree}"]);
    assert!(build_tree(&f.repo, &f.prepared, &tree, b"ok\0", b"ok\0").is_err());
}

#[test]
fn rejects_symlinks_directories_and_missing_files() {
    let f = Fixture::new();
    symlink(f.repo.join("stale.txt"), f.prepared.join("link")).unwrap();
    symlink(&f.repo, f.prepared.join("parent")).unwrap();
    fs::create_dir(f.prepared.join("directory")).unwrap();
    for name in ["link", "parent/stale.txt", "directory", "missing"] {
        assert!(f.build(&[name], &[name]).is_err());
    }
    let linked = f.root.join("linked-root");
    symlink(&f.prepared, &linked).unwrap();
    assert!(build_tree(&f.repo, &linked, &f.base, b"link\0", b"link\0").is_err());
}

#[test]
fn rejects_file_directory_collision_with_destination_owned_file() {
    let f = Fixture::new();
    write(
        &f.prepared,
        "stale.txt/child",
        b"must not replace an owned file",
    );
    assert!(
        f.build(&["stale.txt/child"], &["stale.txt/child"])
            .unwrap_err()
            .to_string()
            .contains("collision")
    );
    assert!(
        f.build(&["stale.txt", "stale.txt/child"], &["stale.txt/child"])
            .is_ok()
    );
}

#[test]
fn binary_bytes_do_not_pass_through_attributes_or_line_ending_filters() {
    let f = Fixture::new();
    write(&f.repo, ".gitattributes", b"*.txt text eol=lf\n");
    git(&f.repo, &["add", ".gitattributes"]);
    git(&f.repo, &["commit", "-qm", "attributes"]);
    write(&f.prepared, "raw.txt", b"line\r\n");
    let base = git(&f.repo, &["rev-parse", "HEAD"]);
    let tree = build_tree(&f.repo, &f.prepared, &base, b"raw.txt\0", b"raw.txt\0").unwrap();
    let out = Command::new("git")
        .arg("-C")
        .arg(&f.repo)
        .args(["show", &format!("{tree}:raw.txt")])
        .output()
        .unwrap();
    assert!(out.status.success());
    assert_eq!(out.stdout, b"line\r\n");
}

#[test]
fn batch_larger_than_pipe_capacity_does_not_deadlock() {
    let f = Fixture::new();
    let names: Vec<_> = (0..1500)
        .map(|i| format!("{}-{i}", "long-name-".repeat(12)))
        .collect();
    for name in &names {
        write(&f.prepared, name, b"shared blob");
    }
    let refs: Vec<_> = names.iter().map(String::as_str).collect();
    assert!(f.build(&refs, &refs).is_ok());
}
