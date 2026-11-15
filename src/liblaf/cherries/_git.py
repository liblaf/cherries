# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Native Git snapshots and self-contained Git/LFS archive transfer."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

_REF = "refs/cherries/runs/"
_POINTER = b"version https://git-lfs.github.com/spec/v1\n"


def _command(repo: Path, *args: str) -> list[str]:
    location = (
        [f"--git-dir={repo}", f"--work-tree={repo}"]
        if (repo / "HEAD").is_file() and (repo / "objects").is_dir()
        else ["-C", str(repo)]
    )
    return [
        "git",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        *location,
        *args,
    ]


def _git(
    repo: Path,
    *args: str,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
    required: bool = True,
) -> bytes:
    result = subprocess.run(
        _command(repo, *args),
        input=data,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", **(env or {})},
    )
    if result.returncode and required:
        raise RuntimeError(
            f"Git {' '.join(args[:2])} in {repo}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout if result.returncode == 0 else b""


def _copy_git(source: Path, destination: Path, roots: set[str]) -> None:
    # A full pack has no dependency on destination objects or source alternates.
    # Explicit plumbing also works for a removed submodule whose configured
    # worktree no longer exists. Stream large packs instead of buffering them.
    with tempfile.TemporaryFile() as revisions, tempfile.TemporaryFile() as errors:
        revisions.write(("\n".join(sorted(roots)) + "\n").encode())
        revisions.seek(0)
        process = subprocess.Popen(
            _command(source, "pack-objects", "--stdout", "--revs"),
            stdin=revisions,
            stdout=subprocess.PIPE,
            stderr=errors,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        )
        try:
            result = subprocess.run(
                _command(destination, "index-pack", "--stdin"),
                stdin=process.stdout,
                capture_output=True,
                check=False,
            )
        finally:
            if process.stdout is not None:
                process.stdout.close()
            status = process.wait()
        if status or result.returncode:
            errors.seek(0)
            raise RuntimeError(
                "Git object transfer failed: "
                + (errors.read() + result.stderr).decode(errors="replace")
            )


def _common(repo: Path) -> Path:
    value = Path(os.fsdecode(_git(repo, "rev-parse", "--git-common-dir").strip()))
    return (value if value.is_absolute() else repo / value).resolve()


def _oid(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", ref, required=False).decode().strip()


def _excluded(name: str) -> bool:
    parts = Path(name).parts
    return bool(
        parts
        and (
            parts[0] == "cherries"
            or (
                parts[0] == "exp"
                and any(p in {"data", "figs", "tmp"} for p in parts[1:])
            )
        )
    )


def _index(
    repo: Path, *, env: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    result = {}
    for row in _git(repo, "ls-files", "--stage", "-z", env=env).split(b"\0"):
        if row:
            header, name = row.split(b"\t", 1)
            mode, oid, _stage = header.decode().split()
            result[os.fsdecode(name)] = (mode, oid)
    return result


def snapshot(repo: Path, run_id: str) -> str:
    """Record ending worktree bytes without changing HEAD or the real index."""
    repo = repo.resolve()
    head = _oid(repo, "HEAD")
    staged = _index(repo)
    with tempfile.TemporaryDirectory(prefix="cherries-index-") as folder:
        env = {
            "GIT_INDEX_FILE": str(Path(folder) / "index"),
            "GIT_LITERAL_PATHSPECS": "1",
        }
        _git(repo, "read-tree", head or "--empty", env=env)
        baseline = _index(repo, env=env)
        names = set(baseline) | set(staged)
        names.update(
            os.fsdecode(p)
            for p in _git(
                repo, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0")
            if p
        )
        # Rebuild from the selected current bytes. Force-add also retains ignored
        # source that the user explicitly staged in their own index.
        if baseline:
            _git(
                repo,
                "update-index",
                "--force-remove",
                "-z",
                "--stdin",
                env=env,
                data=b"\0".join(os.fsencode(p) for p in baseline) + b"\0",
            )
        ordinary = []
        for name in sorted(names):
            if _excluded(name):
                continue
            path = repo / name
            entry = staged.get(name, baseline.get(name))
            if entry and entry[0] == "160000":
                if not path.exists():
                    continue
                commit = (
                    snapshot(path, run_id) if (path / ".git").exists() else entry[1]
                )
                _git(
                    repo,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"160000,{commit},{name}",
                    env=env,
                )
            elif path.is_file() or path.is_symlink():
                ordinary.append(name)
        if ordinary:
            _git(
                repo,
                "add",
                "--force",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                data=b"\0".join(os.fsencode(p) for p in ordinary) + b"\0",
                env=env,
            )
        tree = _git(repo, "write-tree", env=env).decode().strip()
    if head and tree == _oid(repo, f"{head}^{{tree}}"):
        commit = head
    else:
        commit = (
            _git(
                repo,
                "-c",
                "user.name=Cherries",
                "-c",
                "user.email=cherries@localhost",
                "commit-tree",
                tree,
                *(["-p", head] if head else []),
                data=f"Cherries run {run_id}\n".encode(),
            )
            .decode()
            .strip()
        )
    _git(
        repo, "update-ref", "--stdin", data=f"create {_REF}{run_id} {commit}\n".encode()
    )
    return commit


def _module_names(repo: Path, commit: str) -> dict[str, str]:
    result = {}
    data = _git(
        repo,
        "config",
        "-z",
        "--blob",
        f"{commit}:.gitmodules",
        "--get-regexp",
        r"^submodule\..*\.path$",
        required=False,
    )
    for row in data.split(b"\0"):
        if row:
            key, value = row.split(b"\n", 1)
            result[os.fsdecode(value)] = os.fsdecode(key)[
                len("submodule.") : -len(".path")
            ]
    return result


def _child(repo: Path, path: str, name: str, *, create: bool = False) -> Path:
    common = _common(repo)
    worktree = repo / path
    bare = _git(repo, "rev-parse", "--is-bare-repository").strip() == b"true"
    if bare:
        candidates = [common / "modules" / path]
    else:
        candidates = [common / "modules" / name]
        if (worktree / ".git").exists():
            candidates.append(worktree)
        candidates.append(common / "modules" / path)
    for candidate in candidates:
        if (candidate / "HEAD").exists() or (candidate / ".git").exists():
            return candidate
    if create:
        return common / "modules" / path
    raise RuntimeError(f"Missing submodule repository: {repo}: {path}")


def _objects(repo: Path, roots: set[str]) -> dict[str, tuple[str, int]]:
    if not roots:
        return {}
    listing = _git(
        repo,
        "rev-list",
        "--objects",
        "--stdin",
        data=("\n".join(sorted(roots)) + "\n").encode(),
    )
    oids = {row.split(b" ", 1)[0] for row in listing.splitlines()}
    data = _git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        data=b"\n".join(sorted(oids)) + b"\n",
    )
    result = {}
    for row in data.splitlines():
        oid, kind, size = row.decode().split()
        result[oid] = (kind, int(size))
    return result


def _pointer(data: bytes) -> tuple[str, int] | None:
    if not data.startswith(_POINTER):
        return None
    match = re.fullmatch(
        rb"version https://git-lfs.github.com/spec/v1\n"
        rb"oid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n",
        data,
    )
    if match is None:
        raise RuntimeError("Invalid source Git LFS pointer")
    return match[1].decode(), int(match[2])


def _complete(repo: Path) -> None:
    common = _common(repo)
    if (common / "shallow").exists() or any(
        (common / "objects/pack").glob("*.promisor")
    ):
        raise RuntimeError(f"Incomplete source history: {repo}")
    if (
        _git(repo, "rev-parse", "--is-bare-repository").strip() == b"true"
        and (common / "objects/info/alternates").exists()
    ):
        raise RuntimeError(f"Archive depends on external Git alternates: {repo}")


def _inspect(
    repo: Path, roots: set[str]
) -> tuple[dict[str, int], dict[tuple[str, str], set[str]]]:
    """Inspect the whole history, including gitlinks absent from the latest tree."""
    _complete(repo)
    lfs: dict[str, int] = {}
    children: dict[tuple[str, str], set[str]] = defaultdict(set)
    for oid, (kind, size) in _objects(repo, roots).items():
        if kind == "blob" and size <= 4096:
            pointer = _pointer(_git(repo, "cat-file", "blob", oid))
            if pointer:
                digest, length = pointer
                if digest in lfs and lfs[digest] != length:
                    raise RuntimeError(f"Conflicting LFS object sizes: {digest}")
                lfs[digest] = length
        elif kind == "commit":
            names = None
            for row in _git(repo, "ls-tree", "-r", "-z", oid).split(b"\0"):
                if not row:
                    continue
                header, raw_path = row.split(b"\t", 1)
                mode, _kind, child_oid = header.decode().split()
                if mode == "160000":
                    if names is None:
                        names = _module_names(repo, oid)
                    path = os.fsdecode(raw_path)
                    children[path, names.get(path, path)].add(child_oid)
    return lfs, children


def _lfs_path(repo: Path, digest: str) -> Path:
    return _common(repo) / "lfs" / "objects" / digest[:2] / digest[2:4] / digest


def _lfs_source(repo: Path, digest: str) -> Path:
    configured = _git(
        repo, "config", "--path", "--get", "lfs.storage", required=False
    ).strip()
    if configured:
        root = Path(os.fsdecode(configured))
        if not root.is_absolute():
            root = _common(repo) / root
        path = root / "objects" / digest[:2] / digest[2:4] / digest
        if path.is_file():
            return path
    return _lfs_path(repo, digest)


def _check_lfs(path: Path, digest: str, size: int) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
        raise RuntimeError(f"Missing or invalid LFS payload: {path}")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise RuntimeError(f"Corrupt LFS payload: {path}")


def read_file(repo: Path, commit: str, path: str) -> bytes:
    """Read snapshot bytes, hydrating source LFS from the existing local cache."""
    data = _git(repo, "show", f"{commit}:{path}")
    reference = _pointer(data)
    if reference is None:
        return data
    digest, size = reference
    payload = _lfs_source(repo, digest)
    _check_lfs(payload, digest, size)
    return payload.read_bytes()


def _ensure(repo: Path, source: Path) -> None:
    if not (repo / "HEAD").exists() and not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        algorithm = _git(source, "rev-parse", "--show-object-format").decode().strip()
        _git(repo, "init", "--bare", f"--object-format={algorithm}", ".")


def _copy_lfs(src: Path, dst: Path, lfs: dict[str, int], roots: set[str]) -> None:
    if any(not _lfs_source(src, digest).is_file() for digest in lfs):
        _git(src, "lfs", "fetch", "--all", "origin", *sorted(roots))
    for digest, size in lfs.items():
        original, target = _lfs_source(src, digest), _lfs_path(dst, digest)
        _check_lfs(original, digest, size)
        if target.exists():
            _check_lfs(target, digest, size)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)


def transfer(source: Path, destination: Path, run_id: str) -> None:
    """Copy one run ref and its complete Git, recursive gitlink and LFS closure."""
    source, destination = source.resolve(), destination.resolve()
    ref = _REF + run_id
    commit = _oid(source, ref)
    if not commit:
        raise RuntimeError(f"Missing run ref: {source}: {ref}")
    seen: dict[tuple[Path, Path], set[str]] = defaultdict(set)

    def visit(src: Path, dst: Path, roots: set[str]) -> None:
        _ensure(dst, src)
        key = (_common(src), _common(dst))
        if roots <= seen[key]:
            return
        seen[key].update(roots)
        lfs, children = _inspect(src, roots)
        for (path, name), child_roots in children.items():
            visit(
                _child(src, path, name),
                _child(dst, path, name, create=True),
                child_roots,
            )
        if key[0] != key[1]:
            _copy_git(src, dst, roots)
        _copy_lfs(src, dst, lfs, roots)
        child_ref = _oid(src, ref)
        if child_ref:
            # A run's child ref can be absent from historical parent gitlinks.
            # Include its own complete closure before publishing the same ref.
            if child_ref not in seen[key]:
                visit(src, dst, {child_ref})
            existing = _oid(dst, ref)
            if existing and existing != child_ref:
                raise RuntimeError(f"Conflicting immutable run ref: {dst}: {ref}")
            if not existing:
                _git(
                    dst,
                    "update-ref",
                    "--stdin",
                    data=f"create {ref} {child_ref}\n".encode(),
                )

    visit(source, destination, {commit})
    verify(destination, run_id, commit)


def verify(repo: Path, run_id: str, commit: str) -> None:
    """Read-only verification of a run's full native Git/LFS closure."""
    repo = repo.resolve()
    if _oid(repo, _REF + run_id) != commit:
        raise RuntimeError(f"Run commit/ref mismatch: {repo}: {run_id}")
    seen: dict[Path, set[str]] = defaultdict(set)

    def visit(current: Path, roots: set[str]) -> None:
        common = _common(current)
        if roots <= seen[common]:
            return
        seen[common].update(roots)
        _git(current, "fsck", "--full", "--no-reflogs", "--no-dangling", *sorted(roots))
        lfs, children = _inspect(current, roots)
        for digest, size in lfs.items():
            _check_lfs(_lfs_source(current, digest), digest, size)
        for (path, name), child_roots in children.items():
            visit(_child(current, path, name), child_roots)

    visit(repo, {commit})


def _repositories(repo: Path) -> dict[Path, Path]:
    common = _common(repo)
    result = {common: repo}
    modules = common / "modules"
    if modules.exists():
        for directory, subdirs, _files in os.walk(modules):
            current = Path(directory)
            if (current / "HEAD").is_file() and (current / "objects").is_dir():
                result[current.resolve()] = current
                subdirs[:] = [name for name in subdirs if name == "modules"]
    return result


def _roots(repo: Path) -> set[str]:
    result = set(
        _git(repo, "for-each-ref", "--format=%(objectname)").decode().splitlines()
    )
    # Reflog entries protect both their old and new OIDs, including an old
    # value which never appeared as a new value in another retained entry.
    common = _common(repo)
    logs = [common / "logs", *(common / "worktrees").glob("*/logs")]
    for folder in logs:
        for log in folder.rglob("*"):
            if log.is_file():
                for row in log.read_bytes().splitlines():
                    for raw in row.split(b" ", 2)[:2]:
                        if re.fullmatch(
                            rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", raw
                        ) and raw.strip(b"0"):
                            result.add(raw.decode())
    if head := _oid(repo, "HEAD"):
        result.add(head)
    # Preserve the user's staged blobs as well as Git's normal ref/reflog roots.
    result.update(oid for mode, oid in _index(repo).values() if mode != "160000")
    return result


def gc(repo: Path, *, dry_run: bool = False) -> dict[str, int]:  # noqa: C901, PLR0912
    """Collect unreachable Git/LFS objects, retaining historical submodule links."""
    repo = repo.resolve()
    repositories = _repositories(repo)
    protected = {common: _roots(path) for common, path in repositories.items()}
    processed: dict[Path, set[str]] = defaultdict(set)
    lfs_roots: dict[Path, set[str]] = defaultdict(set)
    pending = list(repositories)
    while pending:
        common = pending.pop()
        roots = protected[common]
        if roots <= processed[common]:
            continue
        processed[common].update(roots)
        current = repositories[common]
        lfs, children = _inspect(current, roots)
        lfs_roots[common].update(lfs)
        # Index gitlinks also protect staged submodule commits.
        names = (
            _module_names(current, _oid(current, "HEAD"))
            if _oid(current, "HEAD")
            else {}
        )
        for name, (mode, oid) in _index(current).items():
            if mode == "160000":
                children.setdefault((name, names.get(name, name)), set()).add(oid)
        for (path, name), child_roots in children.items():
            child = _child(current, path, name)
            child_common = _common(child)
            if child_common not in repositories:
                repositories[child_common] = child
                protected[child_common] = _roots(child)
            if (
                not child_roots <= protected[child_common]
                or child_common not in processed
            ):
                protected[child_common].update(child_roots)
                pending.append(child_common)
    count = size = 0
    for common, current in repositories.items():
        retained = _objects(current, protected[common])
        listing = _git(
            current,
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objectsize:disk)",
        )
        for row in listing.decode().splitlines():
            oid, disk_size = row.split()
            if oid not in retained:
                count += 1
                size += int(disk_size)
        unused_lfs = [
            path
            for path in (common / "lfs" / "objects").glob("*/*/*")
            if path.is_file() and path.name not in lfs_roots[common]
        ]
        count += len(unused_lfs)
        size += sum(path.stat().st_size for path in unused_lfs)
        if not dry_run:
            # Git does not traverse gitlinks itself. Temporary native refs keep
            # inherited child history alive while its repository is repacked.
            refs = [f"refs/cherries/gc/{oid}" for oid in protected[common]]
            try:
                for ref, oid in zip(refs, protected[common], strict=True):
                    _git(current, "update-ref", ref, oid)
                _git(
                    current,
                    "-c",
                    "gc.reflogExpire=never",
                    "-c",
                    "gc.reflogExpireUnreachable=never",
                    "gc",
                    "--prune=now",
                    "--quiet",
                )
            finally:
                for ref in refs:
                    _git(current, "update-ref", "-d", ref)
            for path in unused_lfs:
                path.unlink()
    return {"objects": count, "bytes": size}


def remove(repo: Path, run_id: str) -> None:
    """Delete only this run's refs in the root and native module repositories."""
    for current in _repositories(repo.resolve()).values():
        _git(current, "update-ref", "-d", _REF + run_id)
