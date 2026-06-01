from __future__ import annotations

from typing import Any

from liblaf.cherries.core.others import OthersManager
from liblaf.cherries.core.params import ParamsManager


class RecordingParamPlugin:
    def __init__(self) -> None:
        self.param_calls: list[tuple[str, Any]] = []
        self.params_calls: list[dict[str, Any]] = []

    def log_param(self, name: str, value: Any) -> None:
        self.param_calls.append((name, value))

    def log_params(self, params: dict[str, Any]) -> None:
        self.params_calls.append(params)


class RecordingOtherPlugin:
    def __init__(self) -> None:
        self.other_calls: list[tuple[str, Any]] = []
        self.others_calls: list[dict[str, Any]] = []

    def log_other(self, name: str, value: Any) -> None:
        self.other_calls.append((name, value))

    def log_others(self, others: dict[str, Any]) -> None:
        self.others_calls.append(others)


def test_params_manager_flattens_storage_and_restores_nested_view() -> None:
    plugin = RecordingParamPlugin()
    manager = ParamsManager(plugins=plugin)

    manager.log_param("seed", 42)
    manager.log_params({"model": {"layers": 3}, "optimizer": {"lr": 0.001}})

    assert manager.get_param("model/layers") == 3
    assert manager.get_params() == {
        "seed": 42,
        "model": {"layers": 3},
        "optimizer": {"lr": 0.001},
    }
    assert plugin.param_calls == [("seed", 42)]
    assert plugin.params_calls == [{"model/layers": 3, "optimizer/lr": 0.001}]


def test_others_manager_flattens_storage_and_restores_nested_view() -> None:
    plugin = RecordingOtherPlugin()
    manager = OthersManager(plugins=plugin)

    manager.log_other("hostname", "worker-1")
    manager.log_others({"git": {"sha": "abc123"}, "run": {"tag": "debug"}})

    assert manager.get_other("git/sha") == "abc123"
    assert manager.get_others() == {
        "hostname": "worker-1",
        "git": {"sha": "abc123"},
        "run": {"tag": "debug"},
    }
    assert plugin.other_calls == [("hostname", "worker-1")]
    assert plugin.others_calls == [{"git/sha": "abc123", "run/tag": "debug"}]
