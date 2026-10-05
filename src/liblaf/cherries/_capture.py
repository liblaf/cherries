# Copyright (c) 2026 liblaf
"""Record and reconstruct Git evidence without changing an active checkout."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def _git(directory: Path, *args: str, required: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        check=False,
    )
    if required and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout if result.returncode == 0 else b""


def _repo_root(path: Path) -> Path | None:
    root = _git(path, "rev-parse", "--show-toplevel", required=False).strip()
    return Path(os.fsdecode(root)).resolve() if root else None


def _editable_roots() -> list[Path]:
    roots: list[Path] = []
    for dist in importlib.metadata.distributions():
        value = dist.read_text("direct_url.json")
        if not value:
            continue
        try:
            data = json.loads(value)
            parsed = urlparse(data.get("url", ""))
            if data.get("dir_info", {}).get("editable") and parsed.scheme == "file":
                path = Path(unquote(parsed.path))
                if path.is_dir():
                    roots.append(path.resolve())
        except (ValueError, TypeError):
            continue
    return roots


def _repositories(project: Path, roots: list[str]) -> list[Path]:
    candidates = [project, *(project / root for root in roots), *_editable_roots()]
    result: set[Path] = set()
    while candidates:
        path = candidates.pop()
        if not path.is_dir():
            continue
        root = _repo_root(path)
        if root is None or root in result:
            continue
        result.add(root)
        modules = root / ".gitmodules"
        if modules.exists():
            listing = _git(
                root,
                "config",
                "--file",
                ".gitmodules",
                "--get-regexp",
                "path",
                required=False,
            )
            for line in listing.decode(errors="replace").splitlines():
                _, _, relative = line.partition(" ")
                child = (root / relative).resolve()
                if child.is_relative_to(root) and child.exists():
                    candidates.append(child)
    return sorted(result, key=str)


def capture_source(
    project: Path, entrypoint: Path, target: Path, settings: dict[str, Any]
) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    if entrypoint.is_file():
        shutil.copy2(entrypoint, target / "entrypoint.py")
    entries = []
    for repo in _repositories(
        project,
        settings.get("capture", {}).get("roots", ["libs/apple", "libs/melon", "tools"]),
    ):
        relative = (
            repo.relative_to(project).as_posix()
            if repo.is_relative_to(project)
            else "external/"
            + repo.name
            + "-"
            + hashlib.sha256(os.fsencode(repo)).hexdigest()[:12]
        )
        folder = target / "git" / (relative if relative != "." else "project")
        folder.mkdir(parents=True, exist_ok=True)
        head = _git(repo, "rev-parse", "HEAD", required=False).decode().strip() or None
        patch = (
            _git(
                repo,
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=dirty",
                "HEAD",
                required=True,
            )
            if head
            else b""
        )
        status = _git(repo, "status", "--porcelain=v1", "-z")
        (folder / "working-tree.patch").write_bytes(patch)
        (folder / "status").write_bytes(status)
        untracked = []
        for raw in _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(
            b"\0"
        ):
            if not raw:
                continue
            path = Path(os.fsdecode(raw))
            source = repo / path
            if any(
                part
                in {
                    "data",
                    "outputs",
                    "tmp",
                    "scratch",
                    ".cherries",
                    ".venv",
                    "node_modules",
                }
                for part in path.parts
            ):
                continue
            if (
                source.suffix
                not in {
                    ".py",
                    ".toml",
                    ".yaml",
                    ".yml",
                    ".cpp",
                    ".h",
                    ".hpp",
                    ".cu",
                    ".rs",
                    ".sh",
                }
                or not source.is_file()
            ):
                continue
            if (
                source.resolve().is_relative_to(target.resolve())
                or source.stat().st_size > 4 * 1024 * 1024
            ):
                continue
            destination = folder / "untracked" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            untracked.append(
                {
                    "path": path.as_posix(),
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            )
        topology = _git(
            repo, "submodule", "status", "--recursive", required=False
        ).decode(errors="replace")
        evidence = {
            "path": relative,
            "original_path": str(repo),
            "head": head,
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "untracked": untracked,
            "submodules": topology,
            "base_available_locally": bool(head),
        }
        (folder / "commit.json").write_text(
            json.dumps(evidence, sort_keys=True, indent=2) + "\n"
        )
        entries.append(evidence)
    selected = []
    for relative in settings.get("capture", {}).get("files", []):
        source = project / relative
        if (
            not source.resolve().is_relative_to(project.resolve())
            or not source.is_file()
        ):
            msg = f"explicit source file is missing or escapes the project: {relative}"
            raise ValueError(msg)
        destination = target / "selected" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        selected.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )
    entry_hash = (
        hashlib.sha256((target / "entrypoint.py").read_bytes()).hexdigest()
        if (target / "entrypoint.py").exists()
        else None
    )
    fingerprint = {
        "repositories": [
            {
                key: value
                for key, value in entry.items()
                if key not in {"original_path", "base_available_locally"}
            }
            for entry in entries
        ],
        "entrypoint": entry_hash,
        "selected": selected,
    }
    return {
        "boundary": "main_after_imports",
        "repositories": entries,
        "selected": selected,
        "entrypoint_sha256": entry_hash,
        "fingerprint": hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True).encode()
        ).hexdigest(),
        "replay_verified": False,
    }


def capture_environment(project: Path, target: Path) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    for name in ("pyproject.toml", "uv.lock"):
        if (project / name).exists():
            shutil.copy2(project / name, target / name)
    packages = sorted(
        {
            (dist.metadata.get("Name", ""), dist.version)
            for dist in importlib.metadata.distributions()
        }
    )
    value = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": dict(packages),
        "environment": {
            name: os.environ[name]
            for name in (
                "PYTHONHASHSEED",
                "CUDA_VISIBLE_DEVICES",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
            )
            if name in os.environ
        },
        "environment_artifacts_captured": False,
    }
    (target / "runtime.json").write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n"
    )
    return value


def prepare_replay(store: Any, run_id: str, workspace: Path) -> dict[str, Any]:
    """Reconstruct saved Git evidence locally without running the experiment."""
    run_id = store.resolve_id(run_id)
    receipt = store.read_record(run_id)["record"]
    if (
        receipt.get("kind") != "experiment"
        or receipt.get("source_stability") is not True
    ):
        msg = "replay requires a source-stable experiment record, not incomplete legacy provenance"
        raise RuntimeError(msg)
    repositories = receipt.get("source", {}).get("repositories", [])
    root = next((entry for entry in repositories if entry["path"] == "."), None)
    if root is None or not root.get("head"):
        msg = "record has no reconstructable project Git base"
        raise RuntimeError(msg)
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    project = workspace / Path(root["original_path"]).name
    manifest = store.read_manifest(run_id)["files"]
    reason = "replay:" + str(workspace)
    store.hold(run_id, reason)
    try:
        for entry in sorted(
            repositories,
            key=lambda item: (item["path"] != ".", item["path"].count("/")),
        ):
            _replay_repository(store, run_id, entry, project, workspace, manifest)
        for binding in manifest:
            if binding["path"].startswith("source/selected/"):
                store.materialize(
                    run_id,
                    binding["path"],
                    project / binding["path"].removeprefix("source/selected/"),
                )
        script = _replay_entrypoint(store, run_id, receipt, project)
        for name in ("pyproject.toml", "uv.lock"):
            if any(binding["path"] == "environment/" + name for binding in manifest):
                store.materialize(run_id, "environment/" + name, project / name)
        inputs = {
            binding["source"]: "run:" + run_id + "/" + binding["staged_path"]
            for binding in receipt.get("input_bindings", [])
        }
        mapping = workspace / "inputs.json"
        mapping.write_text(json.dumps(inputs, sort_keys=True, indent=2) + "\n")
        return {
            "run_id": run_id,
            "project": str(project),
            "entrypoint": str(script),
            "argv": receipt.get("argv", []),
            "input_mapping": str(mapping),
            "reader_hold": reason,
            "replay_verified": False,
        }
    except BaseException:
        store.release_hold(run_id, reason)
        raise


def _replay_repository(
    store: Any,
    run_id: str,
    entry: dict[str, Any],
    project: Path,
    workspace: Path,
    manifest: list[dict[str, Any]],
) -> None:
    source = Path(entry["original_path"])
    if not entry.get("head") or not (source / ".git").exists():
        msg = f"Git base is unavailable: {entry['path']}"
        raise RuntimeError(msg)
    relative = entry["path"]
    if relative != "." and (
        Path(relative).is_absolute() or ".." in Path(relative).parts
    ):
        msg = "saved repository path escapes replay workspace"
        raise ValueError(msg)
    destination = (
        project
        if relative == "."
        else workspace / source.name
        if relative.startswith("external/")
        else project / relative
    )
    if not destination.resolve().is_relative_to(workspace.resolve()):
        msg = "saved repository path escapes replay workspace"
        raise ValueError(msg)
    if destination.exists() and not any(destination.iterdir()):
        destination.rmdir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _clone_local_repository(source, destination)
    subprocess.run(
        ["git", "-C", str(destination), "checkout", "--detach", entry["head"]],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
    )
    prefix = "source/git/" + ("project" if relative == "." else relative)
    patch = store.materialize(run_id, prefix + "/working-tree.patch")
    if patch.stat().st_size:
        subprocess.run(
            ["git", "-C", str(destination), "apply", "--index", "--binary", str(patch)],
            check=True,
            capture_output=True,
        )
    for binding in manifest:
        if binding["path"].startswith(prefix + "/untracked/"):
            local = binding["path"].removeprefix(prefix + "/untracked/")
            store.materialize(run_id, binding["path"], destination / local)


def _replay_entrypoint(
    store: Any, run_id: str, receipt: dict[str, Any], project: Path
) -> Path:
    script_relative = Path(receipt["entrypoint"])
    if script_relative.is_absolute() or ".." in script_relative.parts:
        msg = "entrypoint must belong to the captured project for replay"
        raise RuntimeError(msg)
    script = project / script_relative
    store.materialize(run_id, "source/entrypoint.py", script)
    return script


def _clone_local_repository(source: Path, destination: Path) -> None:
    command = [
        "git",
        "clone",
        "--local",
        "--no-checkout",
        str(source),
        str(destination),
    ]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode and b"Invalid cross-device link" in result.stderr:
        # Git's immutable object hardlinks cannot cross filesystems.
        if destination.exists():
            shutil.rmtree(destination)
        command.insert(3, "--no-hardlinks")
        result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode:
        msg = result.stderr.decode(errors="replace")
        raise RuntimeError(msg)
