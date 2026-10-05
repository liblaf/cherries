# Copyright (c) 2026 liblaf
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from liblaf.cherries import _cli
from liblaf.cherries.records import Store
from tests.test_source_capture import commit_all, git_repo


def test_replay_runs_saved_script_and_uses_saved_inputs(tmp_path: Path) -> None:
    project = git_repo(tmp_path)
    checkout = Path(__file__).resolve().parents[1]
    (tmp_path / "cherries").symlink_to(checkout, target_is_directory=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname="replay-contract"\nversion="0"\n'
        'requires-python=">=3.12"\ndependencies=["liblaf-cherries"]\n'
        '[tool.uv.sources]\nliblaf-cherries={path="../cherries",editable=true}\n'
    )
    (project / ".gitignore").write_text(".venv/\n")
    script = project / "run.py"
    script.write_text("# initial entrypoint\n")
    commit_all(project)
    raw = tmp_path / "live-input.txt"
    raw.write_text("saved input")
    script.write_text(
        "from liblaf import cherries\n"
        "def experiment():\n"
        f"    data = cherries.input({str(raw)!r})\n"
        "    cherries.output('answer.txt').write_text(data.read_text() + '!')\n"
        "cherries.main(experiment, profile='debug')\n"
    )
    store = Store(tmp_path / "store")
    store.ensure_initialized("replay-collection")
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "CHERRIES_STORAGE": str(store.root),
        "UV_PYTHON": sys.executable,
    }
    environment.pop("UV_FROZEN", None)
    subprocess.run(
        ["uv", "run", "--project", str(project), "python", str(script)],
        cwd=project,
        env=environment,
        check=True,
        capture_output=True,
    )
    [parent] = store.list_records()
    assert store.read_record(parent)["record"]["source_stability"] is True
    raw.write_text("changed live input")
    script.write_text("raise RuntimeError('live script must not execute')\n")
    assert (
        _cli.main(
            [
                "--storage",
                str(store.root),
                "rerun",
                parent,
                "--workspace",
                str(tmp_path / "replay"),
            ]
        )
        == 0
    )
    [child] = [run for run in store.list_records() if run != parent]
    assert store.read_record(child)["parents"] == [parent]
    assert store.materialize(child, "outputs/answer.txt").read_text() == "saved input!"
    assert not store.projection(parent)["holds"]
