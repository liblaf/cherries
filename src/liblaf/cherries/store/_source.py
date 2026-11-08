# Copyright (c) 2026 liblaf
# Domain errors include the path and identity that failed verification.
# ruff: noqa: EM101, EM102, TRY003
"""Archive actual source trees and restore them without their original remotes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ._io import (
    ConflictError,
    IntegrityError,
    StoreError,
    atomic_bytes,
    contained,
    fingerprint,
    fsync_dir,
    hash_file,
    identifier,
    relative_path,
)

_EXCLUDED = frozenset(
    {
        ".cherries",
        ".git",
        ".mypy_cache",
        ".pixi",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "data",
        "dist",
        "env",
        "node_modules",
        "outputs",
        "runs",
        "scratch",
        "venv",
    }
)
_POINTER_VERSION = b"version https://git-lfs.github.com/spec/v1\n"


def _git(
    directory: Path,
    *args: str,
    env: dict[str, str] | None = None,
    data: bytes | None = None,
    required: bool = True,
) -> bytes:
    process = subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "core.fsync=all",
            "-C",
            str(directory),
            *args,
        ],
        input=data,
        capture_output=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if process.returncode and required:
        message = process.stderr.decode(errors="replace").strip()
        raise StoreError(f"Git {' '.join(args[:2])} failed in {directory}: {message}")
    return process.stdout if process.returncode == 0 else b""


def _head(repository: Path) -> str | None:
    return (
        _git(repository, "rev-parse", "--verify", "HEAD", required=False)
        .decode()
        .strip()
        or None
    )


def _repository(project: Any) -> Path:
    value = getattr(project, "repository", None)
    if value is None:
        raise StoreError("the project has no configured source worktree")
    path = Path(value).resolve()
    root = _git(path, "rev-parse", "--show-toplevel").strip()
    if Path(os.fsdecode(root)).resolve() != path:
        raise StoreError(f"source repository must name its Git worktree root: {path}")
    return path


def _archive(project: Any) -> Path:
    return Path(project.archive)


def _source_settings(project: Any) -> dict[str, Any]:
    settings = getattr(project, "settings", {}).get("source")
    if settings is not None:
        return settings
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, dict):
        return {}
    return metadata.get("source", metadata.get("code", {}).get("source", {})) or {}


def _dependencies(project: Any) -> list[tuple[str, Path]]:
    repository = _repository(project)
    configured = _source_settings(project).get("dependencies", {})
    if not isinstance(configured, dict):
        raise IntegrityError("source.dependencies must map names to Git worktrees")
    result: list[tuple[str, Path]] = []
    seen: set[Path] = {repository}
    for name, value in sorted(configured.items()):
        identifier(name)
        path = Path(value).expanduser()
        path = (
            (repository / path).resolve() if not path.is_absolute() else path.resolve()
        )
        if path in seen:
            raise ConflictError(
                f"source repository is registered more than once: {path}"
            )
        if (repository / "external" / name).exists():
            raise ConflictError(
                f"external source checkout would collide with project source: external/{name}"
            )
        root = _git(path, "rev-parse", "--show-toplevel").strip()
        if Path(os.fsdecode(root)).resolve() != path:
            raise IntegrityError(
                f"external source must name its Git worktree root: {path}"
            )
        seen.add(path)
        result.append((name, path))
    return result


def _paths(repository: Path, project: Any) -> tuple[list[str], dict[str, str]]:  # noqa: C901
    """Select tracked content and unignored new files, excluding generated roots."""
    tracked: set[str] = set()
    gitlinks: dict[str, str] = {}
    for row in _git(repository, "ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        header, raw = row.split(b"\t", 1)
        mode, oid, stage = header.decode().split()
        if stage != "0":
            raise IntegrityError(f"unmerged source index entry: {os.fsdecode(raw)}")
        name = os.fsdecode(raw)
        tracked.add(name)
        if mode == "160000":
            gitlinks[name] = oid
    # A staged deletion must not hide a still-present tracked worktree file.
    if _head(repository):
        for row in _git(repository, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
            if not row:
                continue
            header, raw = row.split(b"\t", 1)
            mode, _, oid = header.decode().split()
            name = os.fsdecode(raw)
            tracked.add(name)
            if mode == "160000":
                gitlinks.setdefault(name, oid)
    untracked = {
        os.fsdecode(raw)
        for raw in _git(
            repository, "ls-files", "--others", "--exclude-standard", "-z"
        ).split(b"\0")
        if raw
    }
    settings = _source_settings(project)
    includes = settings.get("include", settings.get("roots", []))
    excludes = settings.get("exclude", [])
    store_path = Path(project.store.root).resolve()

    def selected(name: str) -> bool:
        path = Path(name)
        if name not in tracked and any(part in _EXCLUDED for part in path.parts):
            return False
        if name == "cherries.local.toml" and name not in tracked:
            return False
        if (repository / path).resolve().is_relative_to(store_path):
            return False
        if any(
            path.match(pattern)
            or name == pattern.rstrip("/")
            or name.startswith(pattern.rstrip("/") + "/")
            for pattern in excludes
        ):
            return False
        return (
            name in tracked
            or not includes
            or any(
                path.match(pattern)
                or name == pattern.rstrip("/")
                or name.startswith(pattern.rstrip("/") + "/")
                for pattern in includes
            )
        )

    names = sorted(name for name in tracked | untracked if selected(name))
    return names, {
        name: oid
        for name, oid in gitlinks.items()
        if name in names
        and (repository / name).is_dir()
        and not (repository / name).is_symlink()
    }


def _child_repository(repository: Path, name: str) -> Path:
    child = repository / relative_path(name)
    if not child.is_dir():
        raise IntegrityError(
            f"source submodule is unavailable: {child}; initialize it before recording"
        )
    root = _git(child, "rev-parse", "--show-toplevel", required=False).strip()
    if not root or Path(os.fsdecode(root)).resolve() != child.resolve():
        raise IntegrityError(f"source submodule is uninitialized: {child}")
    return child


def fingerprint_source(project: Any) -> str:
    """Hash the observed source bytes at an execution boundary."""

    def visit(repository: Path, ancestry: set[Path]) -> dict[str, Any]:
        _check_complete_source(repository)
        resolved = repository.resolve()
        if resolved in ancestry:
            raise IntegrityError(f"recursive source submodule: {repository}")
        names, children = _paths(repository, project)
        entries: list[Any] = []
        for name in names:
            source = repository / name
            if name in children:
                entries.append(
                    [
                        name,
                        "gitlink",
                        visit(
                            _child_repository(repository, name), ancestry | {resolved}
                        ),
                    ]
                )
            elif source.is_symlink():
                entries.append([name, "symlink", str(source.readlink())])
            elif source.is_file():
                oid, size = hash_file(source)
                entries.append(
                    [
                        name,
                        "executable" if source.stat().st_mode & 0o111 else "file",
                        oid,
                        size,
                    ]
                )
            elif source.exists():
                raise IntegrityError(
                    f"source path changed to an unsupported type: {source}"
                )
            else:
                entries.append([name, "deleted"])
        return {"head": _head(repository), "files": entries}

    observed = {"main": visit(_repository(project), set())}
    for name, repository in _dependencies(project):
        observed[f"external/{name}"] = visit(repository, set())
    return fingerprint(observed)


def _ensure_archive(path: Path) -> None:
    if path.is_symlink():
        raise IntegrityError(f"source archive is a symbolic link: {path}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(path.parent, "init", "--bare", str(path))
    if _git(path, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise IntegrityError(f"source archive is not a bare repository: {path}")
    for relative in ("objects", "objects/info", "objects/pack"):
        contained(path, relative)
    if any(
        (path / relative).exists()
        for relative in (
            "objects/info/alternates",
            "objects/info/http-alternates",
            "shallow",
        )
    ) or any((path / "objects/pack").glob("*.promisor")):
        raise IntegrityError(
            f"source archive has an external or shallow Git dependency: {path}"
        )
    storage = _git(
        path, "config", "--local", "--get", "lfs.storage", required=False
    ).strip()
    if storage:
        raise IntegrityError(
            f"source archive config overrides its own LFS storage: {path}"
        )


def _pointer(data: bytes) -> tuple[str, int] | None:
    if not data.startswith(_POINTER_VERSION):
        return None
    try:
        text = data.decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise IntegrityError("non-ASCII source Git LFS pointer") from error
    oid = re.search(r"^oid sha256:([0-9a-f]{64})$", text, re.MULTILINE)
    size = re.search(r"^size ([0-9]+)$", text, re.MULTILINE)
    if oid is None or size is None:
        raise IntegrityError("malformed Git LFS pointer in source archive")
    return oid[1], int(size[1])


def _lfs_references(archive: Path) -> dict[str, int]:
    objects = _git(archive, "rev-list", "--objects", "--all").splitlines()
    if not objects:
        return {}
    oids = [row.split(b" ", 1)[0] for row in objects]
    listing = _git(
        archive,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        data=b"\n".join(oids) + b"\n",
    )
    result: dict[str, int] = {}
    for row in listing.splitlines():
        oid, kind, size = row.split()
        if kind != b"blob" or int(size) > 4096:
            continue
        pointer = _pointer(_git(archive, "cat-file", "blob", oid.decode()))
        if pointer is not None:
            digest, payload_size = pointer
            if digest in result and result[digest] != payload_size:
                raise IntegrityError(f"conflicting source LFS sizes: {digest}")
            result[digest] = payload_size
    return result


def _lfs_object(archive: Path, digest: str) -> Path:
    return contained(archive, f"lfs/objects/{digest[:2]}/{digest[2:4]}/{digest}")


def _check_lfs(path: Path, digest: str, size: int) -> None:
    if not path.is_file() or path.is_symlink():
        raise IntegrityError(f"source LFS payload is unavailable: sha256:{digest}")
    if hash_file(path) != ("sha256:" + digest, size):
        raise IntegrityError(f"source LFS payload is corrupt: {path}")


def _copy_lfs(source: Path, target: Path, digest: str, size: int) -> None:
    _check_lfs(source, digest, size)
    if target.exists():
        _check_lfs(target, digest, size)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with source.open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    _check_lfs(temporary, digest, size)
    temporary.replace(target)
    fsync_dir(target.parent)


def _worktree_lfs(repository: Path, digest: str) -> list[Path]:
    common = Path(
        os.fsdecode(_git(repository, "rev-parse", "--git-common-dir").strip())
    )
    if not common.is_absolute():
        common = repository / common
    roots = [common / "lfs"]
    configured = _git(
        repository, "config", "--path", "--get", "lfs.storage", required=False
    ).strip()
    if configured:
        storage = Path(os.fsdecode(configured))
        roots.insert(0, storage if storage.is_absolute() else common / storage)
    return [root / "objects" / digest[:2] / digest[2:4] / digest for root in roots]


def _archive_lfs(repository: Path, archive: Path, commit: str) -> None:
    attempted_fetch = False
    for digest, size in _lfs_references(archive).items():
        target = _lfs_object(archive, digest)
        if target.exists():
            _check_lfs(target, digest, size)
            continue
        candidates = _worktree_lfs(repository, digest)
        source = next((path for path in candidates if path.is_file()), None)
        if source is None and not attempted_fetch:
            attempted_fetch = True
            # Use the user's normal Git/LFS credentials and transport only when
            # bytes required by a retained ref are absent from the local cache.
            _git(repository, "lfs", "fetch", "--all", "origin", commit)
            source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise IntegrityError(
                f"cannot archive missing source LFS payload sha256:{digest}"
            )
        _copy_lfs(source, target, digest, size)


def _check_complete_source(repository: Path) -> None:
    if _git(repository, "rev-parse", "--is-shallow-repository").strip() == b"true":
        message = f"cannot archive a shallow source repository: {repository}; fetch complete history first"
        raise IntegrityError(message)
    common = Path(
        os.fsdecode(_git(repository, "rev-parse", "--git-common-dir").strip())
    )
    common = common if common.is_absolute() else repository / common
    if _git(
        repository, "config", "--get", "extensions.partialclone", required=False
    ).strip() or any((common / "objects/pack").glob("*.promisor")):
        message = f"cannot archive a partial source repository: {repository}; obtain complete objects first"
        raise IntegrityError(message)


def _check_index_gitlinks(
    repository: Path, env: dict[str, str], children: dict[str, str]
) -> None:
    for row in _git(repository, "ls-files", "--stage", "-z", env=env).split(b"\0"):
        if not row:
            continue
        header, raw = row.split(b"\t", 1)
        if header.startswith(b"160000 ") and os.fsdecode(raw) not in children:
            message = f"unregistered nested source repository: {os.fsdecode(raw)}; register a submodule or source dependency"
            raise IntegrityError(message)


def _snapshot_repository(
    project: Any,
    repository: Path,
    archive: Path,
    run_id: str,
    prefix: str,
    modules: list[dict[str, Any]],
) -> tuple[str, str | None]:
    _check_complete_source(repository)
    _ensure_archive(archive)
    head = _head(repository)
    names, children = _paths(repository, project)
    child_commits: dict[str, str] = {}
    for name in sorted(children):
        child = _child_repository(repository, name)
        full_path = f"{prefix}/{name}" if prefix else name
        key = hashlib.sha256(full_path.encode()).hexdigest()[:24]
        relative_archive = f"cherries/submodules/{key}.git"
        child_archive = _archive(project) / relative_archive
        commit, child_head = _snapshot_repository(
            project, child, child_archive, run_id, full_path, modules
        )
        child_commits[name] = commit
        modules.append(
            {
                "path": full_path,
                "archive": relative_archive,
                "ref": f"refs/runs/{run_id}",
                "commit": commit,
                "workspace_head": child_head,
            }
        )

    with tempfile.TemporaryDirectory(prefix="cherries-index-") as folder:
        index = Path(folder) / "index"
        env = {"GIT_INDEX_FILE": str(index), "GIT_LITERAL_PATHSPECS": "1"}
        _git(repository, "read-tree", "--empty", env=env)
        # Start empty so excluded generated content cannot enter via HEAD.
        ordinary = [
            name
            for name in names
            if name not in children
            and ((repository / name).exists() or (repository / name).is_symlink())
        ]
        if ordinary:
            _git(
                repository,
                "add",
                "--force",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                env=env,
                data=b"\0".join(os.fsencode(name) for name in ordinary) + b"\0",
            )
        for name, commit in child_commits.items():
            _git(
                repository,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{commit},{name}",
                env=env,
            )
        _check_index_gitlinks(repository, env, child_commits)
        tree = _git(repository, "write-tree", env=env).decode().strip()
    original_tree = (
        _git(repository, "rev-parse", f"{head}^{{tree}}", required=False)
        .decode()
        .strip()
        if head
        else None
    )
    ref = f"refs/runs/{run_id}"
    previous = (
        _git(archive, "rev-parse", "--verify", ref, required=False).decode().strip()
    )
    previous_tree = (
        _git(archive, "rev-parse", f"{previous}^{{tree}}", required=False)
        .decode()
        .strip()
        if previous
        else None
    )
    previous_head = (
        (
            _git(archive, "rev-parse", f"{previous}^", required=False).decode().strip()
            or None
        )
        if previous and previous != head
        else head
    )
    if previous and previous_tree == tree and previous_head == head:
        commit = previous
    elif head and tree == original_tree:
        commit = head
    else:
        parents = ["-p", head] if head else []
        commit = (
            _git(
                repository,
                "-c",
                "user.name=Cherries",
                "-c",
                "user.email=cherries@localhost",
                "commit-tree",
                tree,
                *parents,
                data=f"Cherries source snapshot for run {run_id}\n".encode(),
            )
            .decode()
            .strip()
        )
    if previous and previous != commit:
        raise ConflictError(
            f"immutable source ref already exists with different code: {ref}"
        )
    stage = f"refs/cherries/staging/{run_id}"
    _git(archive, "fetch", "--no-tags", str(repository), f"{commit}:{stage}")
    _archive_lfs(repository, archive, commit)
    _verify_repository(archive)
    if not previous:
        _git(archive, "update-ref", ref, commit, "0" * len(commit))
    _git(archive, "update-ref", "-d", stage)
    return commit, head


def archived_snapshot(project: Any, run_id: str) -> dict[str, Any] | None:
    """Recover a completed source mapping without resnapshotting live code."""
    relative_path(run_id)
    mapping = _archive(project) / "cherries/runs" / f"{run_id}.json"
    if not mapping.is_file():
        return None
    metadata = json.loads(mapping.read_bytes())
    if metadata.get("ref") != f"refs/runs/{run_id}":
        message = f"archived source mapping has a different run identity: {run_id}"
        raise IntegrityError(message)
    verify_archive(project)
    return metadata


def archive_snapshot(project: Any, run_id: str) -> dict[str, Any]:
    """Save an immutable end ref, recursive submodules, and reachable LFS bytes."""
    relative_path(run_id)
    if "/" in run_id:
        raise IntegrityError(f"invalid source run ID: {run_id}")
    _ensure_archive(_archive(project))
    modules: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for name, repository in _dependencies(project):
        key = hashlib.sha256(f"external/{name}".encode()).hexdigest()[:24]
        relative_archive = f"cherries/submodules/{key}.git"
        dependency_commit, dependency_head = _snapshot_repository(
            project,
            repository,
            _archive(project) / relative_archive,
            run_id,
            f"external/{name}",
            modules,
        )
        dependencies.append(
            {
                "path": f"external/{name}",
                "archive": relative_archive,
                "ref": f"refs/runs/{run_id}",
                "commit": dependency_commit,
                "workspace_head": dependency_head,
            }
        )
    commit, head = _snapshot_repository(
        project, _repository(project), _archive(project), run_id, "", modules
    )
    result = {
        "ref": f"refs/runs/{run_id}",
        "commit": commit,
        "workspace_head": head,
        "submodules": sorted(modules, key=lambda item: item["path"]),
        "dependencies": dependencies,
        "replay_verified": False,
    }
    mapping = _archive(project) / "cherries/runs" / f"{run_id}.json"
    payload = json.dumps(result, sort_keys=True, indent=2).encode() + b"\n"
    if mapping.exists() and mapping.read_bytes() != payload:
        raise ConflictError(f"immutable source mapping differs for run {run_id}")
    atomic_bytes(mapping, payload)
    fsync_dir(_archive(project))
    return result


def _hydrate(archive: Path, worktree: Path) -> None:
    git_dir = worktree / ".git"
    for raw in _git(worktree, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = worktree / os.fsdecode(raw)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 4096:
            continue
        pointer = _pointer(path.read_bytes())
        if pointer is None:
            continue
        digest, size = pointer
        source = _lfs_object(archive, digest)
        _check_lfs(source, digest, size)
        _copy_lfs(source, _lfs_object(git_dir, digest), digest, size)
        mode = path.stat().st_mode
        shutil.copyfile(source, path)
        path.chmod(mode)
    # A local override wins over historical .lfsconfig endpoints. Hydration is
    # performed directly from checked, local bytes and needs no network access.
    _git(worktree, "config", "lfs.url", archive.resolve().as_uri())
    _git(worktree, "config", "remote.origin.lfsurl", archive.resolve().as_uri())


def _checkout_repository(
    archive: Path, destination: Path, ref: str, commit: str
) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise ConflictError(f"source checkout destination is not empty: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _git(
        destination.parent,
        "clone",
        "--no-hardlinks",
        "--no-checkout",
        str(archive.resolve()),
        str(destination),
        env={"GIT_LFS_SKIP_SMUDGE": "1"},
    )
    _git(
        destination,
        "fetch",
        "--no-tags",
        "origin",
        ref,
        env={"GIT_LFS_SKIP_SMUDGE": "1"},
    )
    found = _git(destination, "rev-parse", "FETCH_HEAD").decode().strip()
    if found != commit:
        raise IntegrityError(
            f"source ref {ref} does not match recorded commit {commit}"
        )
    _git(destination, "checkout", "--detach", commit, env={"GIT_LFS_SKIP_SMUDGE": "1"})
    _hydrate(archive, destination)


def _checkout(project: Any, metadata: dict[str, Any], destination: Path) -> Path:
    archive = _archive(project)
    _checkout_repository(archive, destination, metadata["ref"], metadata["commit"])
    modules = sorted(
        [*metadata.get("submodules", []), *metadata.get("dependencies", [])],
        key=lambda item: (item["path"].count("/"), item["path"]),
    )
    for module in modules:
        path = contained(destination, module["path"])
        child_archive = contained(archive, module["archive"])
        _checkout_repository(child_archive, path, module["ref"], module["commit"])
    return destination


def checkout_source(run: Any, destination: str | Path) -> Path:
    """Restore the exact run ref and its submodules and LFS files offline."""
    metadata = run.metadata.get("git", {})
    if not metadata.get("ref") or not metadata.get("commit"):
        raise IntegrityError(f"run {run.id} has no archived source ref")
    return _checkout(run.project, metadata, Path(destination).resolve())


def _verify_repository(archive: Path) -> dict[str, int]:
    _ensure_archive(archive)
    _git(archive, "fsck", "--full", "--no-reflogs")
    refs = _git(archive, "for-each-ref", "--format=%(refname)").splitlines()
    lfs = _lfs_references(archive)
    for digest, size in lfs.items():
        _check_lfs(_lfs_object(archive, digest), digest, size)
    return {"refs": len(refs), "lfs_objects": len(lfs), "lfs_bytes": sum(lfs.values())}


def verify_archive(project: Any, *, offline: bool = False) -> dict[str, Any]:
    """Verify retained Git/LFS closure and optionally perform real offline restores."""
    archive = _archive(project)
    if not archive.exists():
        return {
            "ok": True,
            "refs": 0,
            "lfs_objects": 0,
            "lfs_bytes": 0,
            "offline_checked": 0,
        }
    result: dict[str, Any] = {
        "ok": True,
        **_verify_repository(archive),
        "offline_checked": 0,
    }
    for child in sorted((archive / "cherries/submodules").glob("*.git")):
        values = _verify_repository(child)
        result["lfs_objects"] += values["lfs_objects"]
        result["lfs_bytes"] += values["lfs_bytes"]
    refs = (
        _git(archive, "for-each-ref", "--format=%(refname) %(objectname)", "refs/runs/")
        .decode()
        .splitlines()
    )
    for row in refs:
        ref, commit = row.split()
        mapping = archive / "cherries/runs" / f"{ref.rsplit('/', 1)[1]}.json"
        if not mapping.is_file():
            raise IntegrityError(f"source archive is missing run mapping: {ref}")
        metadata = json.loads(mapping.read_text())
        if metadata.get("commit") != commit or metadata.get("ref") != ref:
            raise IntegrityError(f"source mapping and ref disagree: {ref}")
        for module in [
            *metadata.get("submodules", []),
            *metadata.get("dependencies", []),
        ]:
            child = contained(archive, module["archive"])
            actual = (
                _git(child, "rev-parse", "--verify", module["ref"]).decode().strip()
            )
            if actual != module["commit"]:
                raise IntegrityError(f"source submodule ref mismatch: {module['path']}")
        if offline:
            with tempfile.TemporaryDirectory(prefix="cherries-offline-") as folder:
                _checkout(project, metadata, Path(folder) / "source")
            result["offline_checked"] += 1
    return result


def _copy_repository(source: Path, target: Path) -> None:
    _ensure_archive(target)
    source_refs = (
        _git(source, "for-each-ref", "--format=%(refname) %(objectname)")
        .decode()
        .splitlines()
    )
    for row in source_refs:
        ref, commit = row.split()
        existing = (
            _git(target, "rev-parse", "--verify", ref, required=False).decode().strip()
        )
        if existing and existing != commit:
            raise ConflictError(f"source archive immutable ref conflict: {ref}")
    if source_refs:
        _git(target, "fetch", "--no-tags", str(source.resolve()), "refs/*:refs/*")
    for digest, size in _lfs_references(source).items():
        _copy_lfs(
            _lfs_object(source, digest), _lfs_object(target, digest), digest, size
        )


def copy_archive(source_project: Any, target_project: Any) -> None:
    """Merge immutable refs into an independent archive without shared links."""
    source = _archive(source_project)
    target = _archive(target_project)
    if not source.exists():
        return
    if source.resolve() == target.resolve():
        verify_archive(source_project)
        return
    verify_archive(source_project)
    _copy_repository(source, target)
    for child in sorted((source / "cherries/submodules").glob("*.git")):
        _copy_repository(child, target / "cherries/submodules" / child.name)
    for mapping in sorted((source / "cherries/runs").glob("*.json")):
        destination = target / "cherries/runs" / mapping.name
        if destination.exists() and destination.read_bytes() != mapping.read_bytes():
            raise ConflictError(f"source archive mapping conflict: {mapping.name}")
        atomic_bytes(destination, mapping.read_bytes())
    verify_archive(target_project)
