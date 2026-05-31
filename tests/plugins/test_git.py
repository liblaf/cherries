from datetime import UTC, datetime
from pathlib import Path

import git

from liblaf.cherries import core
from liblaf.cherries.plugins.git import Git


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


def test_git_end_records_final_sha_without_committing_when_disabled(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    (tmp_path / "artifact.txt").write_text("dirty\n")
    run = core.Run()
    run.repo = repo
    plugin = Git(run=run, commit=False)

    plugin.end()

    assert run.get_other("cherries/git/sha") == repo.head.commit.hexsha
    assert repo.is_dirty(untracked_files=True)


def test_git_commit_message_includes_run_summary_with_relative_paths(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    run = core.Run()
    run.repo = repo
    run.run_name = "exp/demo.py"
    run.log_other("cherries/start_time", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    run.log_param("epochs", 3)
    output = tmp_path / "exp" / "data" / "metrics.json"
    output.parent.mkdir(parents=True)
    output.write_text("{}\n")
    run.log_output(output)
    plugin = Git(run=run, commit=True)

    plugin.end()

    message = repo.head.commit.message
    assert message.startswith("chore(exp): exp/demo.py\n\n")
    assert "start_time: 2026-01-02 03:04:05+00:00" in message
    assert "params:\n  epochs: 3" in message
    assert "outputs:\n- exp/data/metrics.json" in message
    assert run.get_other("cherries/git/sha") == repo.head.commit.hexsha
