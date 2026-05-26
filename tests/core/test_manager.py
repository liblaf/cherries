from typing import Any

import attrs
import pytest

from liblaf.cherries import core


@attrs.define
class Recorder(core.Plugin):
    calls: list[str]


def test_delegate_honors_before_and_after_constraints() -> None:
    @attrs.define
    class Comet(Recorder):
        @core.impl(after=("Logging",))
        def start(self) -> None:
            self.calls.append(self.name)

    @attrs.define
    class Local(Recorder):
        @core.impl(before=("Comet",))
        def start(self) -> None:
            self.calls.append(self.name)

    @attrs.define
    class Logging(Recorder):
        @core.impl
        def start(self) -> None:
            self.calls.append(self.name)

    calls: list[str] = []
    manager = core.PluginManager()
    manager.register(Comet(calls))
    manager.register(Local(calls))
    manager.register(Logging(calls))

    manager.delegate("start")

    assert calls.index("Logging") < calls.index("Comet")
    assert calls.index("Local") < calls.index("Comet")


def test_register_invalidates_cached_plugin_order() -> None:
    @attrs.define
    class Comet(Recorder):
        @core.impl
        def start(self) -> None:
            self.calls.append(self.name)

    @attrs.define
    class Local(Recorder):
        @core.impl(before=("Comet",))
        def start(self) -> None:
            self.calls.append(self.name)

    calls: list[str] = []
    manager = core.PluginManager()
    manager.register(Comet(calls))
    manager.delegate("start")
    calls.clear()

    manager.register(Local(calls))
    manager.delegate("start")

    assert calls == ["Local", "Comet"]


def test_delegate_first_result_stops_after_first_value() -> None:
    @attrs.define
    class Empty(Recorder):
        @core.impl
        def get_url(self) -> None:
            self.calls.append(self.name)

    @attrs.define
    class Found(Recorder):
        @core.impl
        def get_url(self) -> str:
            self.calls.append(self.name)
            return "https://example.test/run"

    @attrs.define
    class Later(Recorder):
        @core.impl
        def get_url(self) -> str:
            self.calls.append(self.name)
            return "unreachable"

    calls: list[str] = []
    manager = core.PluginManager()
    manager.register(Empty(calls))
    manager.register(Found(calls))
    manager.register(Later(calls))

    result: Any = manager.delegate("get_url", first_result=True)

    assert result == "https://example.test/run"
    assert calls == ["Empty", "Found"]


def test_delegate_logs_plugin_exceptions_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @attrs.define
    class Broken(Recorder):
        @core.impl
        def start(self) -> None:
            message = "boom"
            raise RuntimeError(message)

    @attrs.define
    class Later(Recorder):
        @core.impl
        def start(self) -> None:
            self.calls.append(self.name)

    calls: list[str] = []
    manager = core.PluginManager()
    manager.register(Broken(calls))
    manager.register(Later(calls))

    manager.delegate("start")

    assert calls == ["Later"]
    assert "Plugin Broken" in caplog.text
