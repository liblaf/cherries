# Copyright (c) 2026 liblaf
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from liblaf.cherries.records import Store


@pytest.mark.parametrize(
    ("arguments", "exit_code"),
    [
        (["--help"], 0),
        (["--unknown"], 2),
        (["--source", "input.txt", "--value", "bad"], 1),
        ([], 1),
    ],
)
def test_config_cli_exits_without_starting_a_run(
    tmp_path: Path, arguments: list[str], exit_code: int
) -> None:
    script = tmp_path / "experiment.py"
    script.write_text(
        "from pathlib import Path\n"
        "from liblaf import cherries\n"
        "class Config(cherries.BaseConfig):\n"
        "    source: str\n"
        "    value: int = 3\n"
        "def main(cfg: Config):\n"
        "    Path('executed.txt').write_text('ran')\n"
        "cherries.main(main)\n"
    )
    store = tmp_path / "store"
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "CHERRIES_STORAGE": str(store),
        "CHERRIES_COMET": "0",
    }
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == exit_code, completed.stderr
    if arguments == ["--help"]:
        assert "--source" in completed.stdout
    assert not (tmp_path / "executed.txt").exists()
    assert not store.exists()


def test_config_cli_values_are_recorded_and_used_by_main(tmp_path: Path) -> None:
    script = tmp_path / "experiment.py"
    script.write_text(
        "from liblaf import cherries\n"
        "class Config(cherries.BaseConfig):\n"
        "    num_steps: int = 3\n"
        "def main(cfg: Config):\n"
        "    cherries.output('result.txt').write_text(str(cfg.num_steps))\n"
        "cherries.main(main)\n"
    )
    store = Store(tmp_path / "store")
    completed = subprocess.run(
        [sys.executable, str(script), "--num-steps", "7"],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "CHERRIES_STORAGE": str(store.root),
            "CHERRIES_COMET": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    [run_id] = store.list_records()
    assert store.read_record(run_id)["record"]["params"]["num_steps"] == 7
    assert store.materialize(run_id, "outputs/result.txt").read_text() == "7"
