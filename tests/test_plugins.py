from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from liblaf.cherries import core
from liblaf.cherries.plugins import comet as comet_module
from liblaf.cherries.plugins.comet import Comet
from liblaf.cherries.plugins.local import Local


def test_local_plugin_copies_working_tree_and_external_artifacts(
    tmp_path: Path,
) -> None:
    working_dir = tmp_path / "exp" / "2026" / "06" / "01" / "demo"
    working_dir.mkdir(parents=True)
    entrypoint = working_dir / "src" / "10-main.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("from liblaf import cherries\n")
    internal = working_dir / "data" / "result.txt"
    internal.parent.mkdir()
    internal.write_text("ok\n")
    external = tmp_path / "external.txt"
    external.write_text("outside\n")
    run = cast(
        "core.Run",
        SimpleNamespace(
            entrypoint=entrypoint,
            project_dir=tmp_path,
            run_key=Path("2026/06/01/demo/10-main/2026-06-01T123045"),
            working_dir=working_dir,
        ),
    )
    plugin = Local(run=run)

    plugin.log_asset(internal)
    plugin.log_asset(external)

    assert (tmp_path / ".cherries" / ".gitignore").read_text() == "*\n"
    assert (plugin.folder / "data" / "result.txt").read_text() == "ok\n"
    assert (plugin.folder / "assets" / "external.txt").read_text() == "outside\n"


def test_comet_plugin_start_records_url_and_forwards_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Experiment:
        url = "https://comet.example/experiment"

        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        def end(self) -> None:
            self.calls.append(("end", (), {}))

        def log_metric(self, *args, **kwargs) -> None:
            self.calls.append(("metric", args, kwargs))

        def log_metrics(self, *args, **kwargs) -> None:
            self.calls.append(("metrics", args, kwargs))

        def log_other(self, *args, **kwargs) -> None:
            self.calls.append(("other", args, kwargs))

        def log_others(self, *args, **kwargs) -> None:
            self.calls.append(("others", args, kwargs))

        def log_parameter(self, *args, **kwargs) -> None:
            self.calls.append(("param", args, kwargs))

        def log_parameters(self, *args, **kwargs) -> None:
            self.calls.append(("params", args, kwargs))

    experiment = Experiment()
    started: dict[str, Any] = {}
    run = core.Run()
    run.repo = None
    run.project_name = "cherries"
    run.run_name = "demo"
    run.tags = ["debug"]

    def start(*, project_name: str, experiment_config: Any) -> Experiment:
        started["project_name"] = project_name
        started["config"] = experiment_config
        return experiment

    monkeypatch.setattr(comet_module.comet, "start", start)
    monkeypatch.setattr(
        comet_module.comet, "get_running_experiment", lambda: experiment
    )

    plugin = Comet(run=run, disabled=True)
    when = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    plugin.start()
    plugin.log_metric("loss", 0.25, step=3, time=when)
    plugin.log_metrics({"train/loss": 0.25}, step=3, time=when)
    plugin.log_other("hostname", "worker-1")
    plugin.log_others({"git/sha": "abc123"})
    plugin.log_param("epochs", 10)
    plugin.log_params({"optimizer/lr": 0.01})
    plugin.end()

    config = started["config"]
    assert started["project_name"] == "cherries"
    assert config.disabled is True
    assert config.name == "demo"
    assert config.tags == ["debug"]
    assert run.get_other("cherries/comet/url") == experiment.url
    assert experiment.calls == [
        ("metric", ("loss", 0.25), {"step": 3}),
        ("metrics", ({"train/loss": 0.25},), {"step": 3}),
        ("other", ("hostname", "worker-1"), {}),
        ("others", ({"git/sha": "abc123"},), {}),
        ("param", ("epochs", 10), {}),
        ("params", ({"optimizer/lr": 0.01},), {}),
        ("end", (), {}),
    ]
