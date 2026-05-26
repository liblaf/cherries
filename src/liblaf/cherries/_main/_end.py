from liblaf.cherries import core


def end() -> None:
    """End the process-global run."""
    core.run.end()
