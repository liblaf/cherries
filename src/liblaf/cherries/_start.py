from collections.abc import Sequence

from environs import Env

from liblaf import cherries


def start(
    *,
    backend: cherries.Backend | None = None,
    enabled: bool | None = None,
    plugins: Sequence[cherries.Plugin] | None = None,
) -> cherries.Experiment:
    backend = backend or cherries.backend_factory()
    if enabled is None:
        enabled = Env().bool("LIBLAF_CHERRIES_ENABLED", True)
    if plugins is None:
        plugins = cherries.default_plugins()
    exp = cherries.Experiment(backend=backend, enabled=enabled, plugins=plugins)
    exp.start()
    return exp


def end() -> None:
    exp: cherries.Experiment = cherries.current_experiment()
    exp.end()
