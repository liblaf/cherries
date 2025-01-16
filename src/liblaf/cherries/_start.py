from collections.abc import Sequence

from liblaf import cherries

_current_run: cherries.Run | None = None


def current_run() -> cherries.Run | None:
    return _current_run


def set_current_run(run: cherries.Run) -> None:
    global _current_run  # noqa: PLW0603
    _current_run = run


def start(
    backend: type[cherries.Run],
    plugins: Sequence[cherries.Plugin] = [],
    *,
    enabled: bool = True,
) -> cherries.Run | None:
    if not enabled:
        return None
    plugins = sorted(plugins, key=lambda plugin: plugin.priority)
    for plugin in plugins:
        if plugin.enabled:
            plugin.pre_start()
    run: cherries.Run = backend()
    run.plugins = plugins
    set_current_run(run)
    for plugin in plugins:
        if plugin.enabled:
            plugin.post_start(run)
    return run


def end(run: cherries.Run | None = None) -> None:
    run = run or current_run()
    if run is None:
        return
    for plugin in reversed(run.plugins):
        if plugin.enabled:
            plugin.pre_end(run)
    run.end()
    for plugin in reversed(run.plugins):
        if plugin.enabled:
            plugin.post_end(run)
