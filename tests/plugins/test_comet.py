from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import git
import pytest

import liblaf.cherries.plugins.comet as comet_module


def test_log_asset_uploads_plain_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    experiment = Mock()
    monkeypatch.setattr(
        comet_module.comet, "get_running_experiment", lambda: experiment
    )
    plugin = comet_module.Comet()
    path: Path = tmp_path / "plot.png"
    metadata: Mapping[str, Any] = {"kind": "figure"}

    plugin.log_asset(path, Path("figs/plot.png"), metadata=metadata)

    experiment.log_asset.assert_called_once_with(
        path, "figs/plot.png", metadata={"kind": "figure"}
    )


def test_log_input_and_output_prefix_names_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = comet_module.Comet()
    calls: list[tuple[Path, Path, dict[str, Any] | None, dict[str, Any]]] = []

    def log_asset(
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        calls.append(
            (
                path,
                name,
                dict(metadata) if metadata is not None else None,
                dict(kwargs),
            )
        )

    monkeypatch.setattr(plugin, "log_asset", log_asset)

    plugin.log_input(
        Path("data.csv"),
        Path("raw/data.csv"),
        metadata={"split": "train"},
        overwrite=True,
    )
    plugin.log_output(Path("metrics.json"), Path("metrics.json"), metadata=None)

    assert calls == [
        (
            Path("data.csv"),
            Path("inputs/raw/data.csv"),
            {"split": "train", "type": "input"},
            {"overwrite": True},
        ),
        (
            Path("metrics.json"),
            Path("outputs/metrics.json"),
            {"type": "output"},
            {},
        ),
    ]


def test_log_asset_defers_git_addressable_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Cherries Test")
        config.set_value("user", "email", "cherries@example.test")
    repo.create_remote("origin", "https://github.com/liblaf/cherries.git")
    path = tmp_path / "artifact.txt"
    path.write_text("artifact")
    repo.index.add(["artifact.txt"])
    repo.index.commit("initial")
    monkeypatch.chdir(tmp_path)
    experiment = Mock()
    monkeypatch.setattr(
        comet_module.comet, "get_running_experiment", lambda: experiment
    )
    plugin = comet_module.Comet()

    plugin.log_asset(path, Path("artifact.txt"), metadata={"kind": "text"})
    plugin.end()

    experiment.log_asset.assert_not_called()
    experiment.log_remote_asset.assert_called_once_with(
        f"https://github.com/liblaf/cherries/raw/{repo.head.commit.hexsha}/artifact.txt",
        "artifact.txt",
        metadata={"kind": "text"},
    )
    experiment.end.assert_called_once_with()
