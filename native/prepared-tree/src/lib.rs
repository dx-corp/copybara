//! Native tree assembly for immutable, already-authorized prepared projections.
//! No policy discovery, config evaluation, credentials, commits, refs, or network.
use std::{
    collections::BTreeSet,
    error::Error,
    fs,
    io::Write,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

struct Scratch(PathBuf);
impl Scratch {
    fn new() -> Result<Self> {
        loop {
            let path = std::env::temp_dir().join(format!(
                "copybara-tree-{}-{}",
                std::process::id(),
                NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
            ));
            match fs::DirBuilder::new().mode(0o700).create(&path) {
                Ok(()) => {
                    let scratch = Self(path);
                    return Ok(scratch);
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(e) => return Err(e.into()),
            }
        }
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn paths(bytes: &[u8]) -> Result<BTreeSet<String>> {
    if !bytes.is_empty() && !bytes.ends_with(&[0]) {
        return Err("manifest must be NUL-terminated".into());
    }
    let mut paths = BTreeSet::new();
    if bytes.is_empty() {
        return Ok(paths);
    }
    for bytes in bytes[..bytes.len() - 1].split(|byte| *byte == 0) {
        let path = std::str::from_utf8(bytes)?;
        if path.is_empty()
            || path.contains(['\\', ':'])
            || path.split('/').any(|part| {
                part.is_empty()
                    || part == "."
                    || part == ".."
                    || part.eq_ignore_ascii_case(".git")
                    || part.ends_with(['.', ' '])
            })
        {
            return Err(format!("unsafe manifest path: {path:?}").into());
        }
        if !paths.insert(path.to_string()) {
            return Err(format!("duplicate manifest path: {path:?}").into());
        }
    }
    Ok(paths)
}

fn git(repo: &Path, index: &Path, args: &[&str], input: &[u8]) -> Result<Vec<u8>> {
    let mut command = Command::new("git");
    command.arg("-C").arg(repo).args(args);
    // Never inherit another checkout's index/object-directory overrides.
    for variable in [
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ] {
        command.env_remove(variable);
    }
    let mut child = command
        .env("GIT_INDEX_FILE", index)
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_NO_REPLACE_OBJECTS", "1")
        .env("GIT_NO_LAZY_FETCH", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    // Write concurrently: batch hash input/output can exceed both pipe buffers.
    let mut stdin = child.stdin.take().ok_or("missing git stdin")?;
    std::thread::scope(|scope| {
        let writer = scope.spawn(move || stdin.write_all(input));
        let output = child.wait_with_output()?;
        let written = writer.join().map_err(|_| "git input writer panicked")?;
        if !output.status.success() {
            return Err(format!(
                "git {}: {}",
                args[0],
                String::from_utf8_lossy(&output.stderr)
            )
            .into());
        }
        written?;
        Ok(output.stdout)
    })
}

fn oid(bytes: &[u8]) -> Result<&str> {
    let value = std::str::from_utf8(bytes)?.trim();
    if ![40, 64].contains(&value.len())
        || !value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("expected full lowercase Git object ID".into());
    }
    Ok(value)
}

fn quote_git_path(path: &Path) -> Result<Vec<u8>> {
    let value = path.to_str().ok_or("prepared root must be UTF-8")?;
    let mut output = vec![b'"'];
    for byte in value.bytes() {
        match byte {
            b'"' | b'\\' => output.extend([b'\\', byte]),
            32..=126 => output.push(byte),
            _ => output.extend(format!("\\{byte:03o}").bytes()),
        }
    }
    output.extend(b"\"\n");
    Ok(output)
}

/// Construct a Git tree using an isolated index. Only unreachable Git objects
/// are written. The caller's worktree, index, HEAD, and refs are untouched.
/// `managed` enumerates ALL old managed paths plus ALL incoming paths; `origin`
/// enumerates only the incoming files. Omitted managed paths are deleted.
/// Callers must supply immutable local inputs and independently authorize both
/// inventories. This is not a sandbox for concurrently malicious writers.
pub fn build_tree(
    destination: &Path,
    prepared: &Path,
    base: &str,
    managed: &[u8],
    origin: &[u8],
) -> Result<String> {
    if oid(base.as_bytes())? != base {
        return Err("base must be an exact object ID".into());
    }
    let managed = paths(managed)?;
    let origin = paths(origin)?;
    if origin.is_empty() || !origin.is_subset(&managed) {
        return Err("origin must be nonempty and contained in managed inventory".into());
    }
    if !fs::symlink_metadata(prepared)?.is_dir() {
        return Err("prepared root must be a non-symlink directory".into());
    }
    let prepared = prepared.canonicalize()?;
    let mut modes = Vec::new();
    let mut inputs = Vec::new();
    for relative in &origin {
        let mut absolute = prepared.clone();
        let components: Vec<_> = relative.split('/').collect();
        for (number, component) in components.iter().enumerate() {
            absolute.push(component);
            let metadata = fs::symlink_metadata(&absolute)?;
            if metadata.file_type().is_symlink()
                || (number + 1 < components.len() && !metadata.is_dir())
                || (number + 1 == components.len() && !metadata.is_file())
            {
                return Err(format!("non-regular origin path: {relative:?}").into());
            }
            if number + 1 == components.len() {
                modes.push(if metadata.permissions().mode() & 0o100 == 0 {
                    "100644"
                } else {
                    "100755"
                });
            }
        }
        inputs.extend(quote_git_path(&absolute)?);
    }
    let scratch = Scratch::new()?;
    let index = scratch.0.join("index");
    // Require a commit, not a mutable ref, tree ID, or revision expression.
    if git(destination, &index, &["cat-file", "-t", base], &[])? != b"commit\n" {
        return Err("base must identify a commit".into());
    }
    let baseline = git(
        destination,
        &index,
        &["ls-tree", "-r", "-z", "--name-only", base],
        &[],
    )?;
    let prior = paths(&baseline)?;
    let final_paths: BTreeSet<_> = prior.difference(&managed).chain(origin.iter()).collect();
    for path in &final_paths {
        let mut parent = Path::new(path.as_str()).parent();
        while let Some(p) = parent {
            if final_paths.contains(&p.to_str().ok_or("non-UTF-8 path")?.to_string()) {
                return Err(format!("file/directory collision at {path:?}").into());
            }
            parent = p.parent();
        }
    }
    git(destination, &index, &["read-tree", base], &[])?;
    let removals: Vec<_> = managed.iter().flat_map(|p| p.bytes().chain([0])).collect();
    git(
        destination,
        &index,
        &["update-index", "--force-remove", "-z", "--stdin"],
        &removals,
    )?;
    let hashes = git(
        destination,
        &index,
        &["hash-object", "-w", "--no-filters", "--stdin-paths"],
        &inputs,
    )?;
    let hashes = std::str::from_utf8(&hashes)?.lines().collect::<Vec<_>>();
    if hashes.len() != origin.len() {
        return Err("Git returned the wrong number of blobs".into());
    }
    let mut entries = Vec::new();
    for ((path, mode), hash) in origin.iter().zip(modes).zip(hashes) {
        oid(hash.as_bytes())?;
        entries.extend(format!("{mode} {hash}\t{path}\0").bytes());
    }
    git(
        destination,
        &index,
        &["update-index", "-z", "--index-info"],
        &entries,
    )?;
    let tree = git(destination, &index, &["write-tree"], &[])?;
    Ok(oid(&tree)?.to_string())
}
