from liblaf.cherries import core


def end() -> None:
    """End the process-global run.

    This is useful for scripts that call [`start`][liblaf.cherries.start]
    manually instead of using [`main`][liblaf.cherries.main].
    """
    core.run.end()
