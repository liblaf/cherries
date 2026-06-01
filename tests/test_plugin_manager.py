from __future__ import annotations

import logging

import pytest

from liblaf.cherries.core.plugin import Plugin, PluginManager, impl


def test_plugin_manager_orders_hooks_by_declared_dependencies() -> None:
    calls: list[str] = []

    class First(Plugin):
        @impl
        def start(self) -> None:
            calls.append("first")

    class Middle(Plugin):
        @impl(after=("First",))
        def start(self) -> None:
            calls.append("middle")

    class Last(Plugin):
        @impl(after=("Middle",))
        def start(self) -> None:
            calls.append("last")

    manager = PluginManager()
    manager.register(Last())
    manager.register(Middle())
    manager.register(First())

    manager.delegate("start")

    assert calls == ["first", "middle", "last"]


def test_plugin_manager_logs_failures_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    class Failing(Plugin):
        @impl
        def start(self) -> None:
            calls.append("failing")
            message = "boom"
            raise RuntimeError(message)

    class Later(Plugin):
        @impl(after=("Failing",))
        def start(self) -> None:
            calls.append("later")

    manager = PluginManager()
    manager.register(Failing())
    manager.register(Later())

    with caplog.at_level(logging.ERROR, logger="liblaf.cherries.core.plugin._manager"):
        manager.delegate("start")

    assert calls == ["failing", "later"]
    assert "Plugin Failing failed in start" in caplog.text
