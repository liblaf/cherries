import logging
from pathlib import Path
from typing import Any

import git
import pytest

from liblaf.cherries.plugins.git_ import Git

logger: logging.Logger = logging.getLogger("liblaf.cherries.plugins.git_")


class GitManager:
    def __init__(self, repo: git.Repo, exp_dir: Path) -> None:
        self.repo = repo
        self.exp_dir = exp_dir
        self.exp_name = "exp/demo.py"
        self.url = "https://example.test/run"
        self.logged: dict[str, Any] = {}

    def get_params(self) -> dict[str, Any]:
        return {"epochs": 3, "lr": 0.01}

    def log_other(self, name: str, value: Any) -> None:
        self.logged[name] = value


def make_repo(tmp_path: Path) -> git.Repo:
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Cherries Test")
        config.set_value("user", "email", "cherries@example.test")
    tracked = tmp_path / "README.md"
    tracked.write_text("demo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    return repo


def test_git_summary_records_reported_paths_and_final_sha(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    exp_dir = tmp_path / "exp"
    exp_dir.mkdir()
    monkeypatch.chdir(exp_dir)
    manager = GitManager(repo, exp_dir)
    plugin = Git(commit=False)
    plugin.manager = manager
    input_path = exp_dir / "data" / "raw.csv"
    output_path = exp_dir / "data" / "metrics.json"
    temp_path = exp_dir / "tmp" / "scratch.txt"

    plugin.log_input(input_path, Path("raw.csv"))
    plugin.log_output(output_path, Path("metrics.json"), report=False)
    plugin.log_temp(temp_path, Path("scratch.txt"))
    with caplog.at_level(logging.INFO, logger=logger.name):
        plugin.end(exc=ValueError("bad input"))

    assert manager.logged == {"cherries.git.sha": repo.head.commit.hexsha}
    assert "name: exp/demo.py" in caplog.text
    assert "url: https://example.test/run" in caplog.text
    assert "params:" in caplog.text
    assert "inputs:" in caplog.text
    assert "temps:" in caplog.text
    assert "outputs:" not in caplog.text
    assert "ValueError: bad input" in caplog.text
