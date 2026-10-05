# Copyright (c) 2026 liblaf
from liblaf.cherries import core, profiles
from liblaf.cherries.profiles import Profile, ProfileLike


def start(profile: ProfileLike | None = None) -> core.Run:
    """Create, configure, and start a run from `profile`.

    Args:
        profile: Profile name, instance, class, or `None` for environment-based
            selection.

    Returns:
        Started run.
    """
    profile: Profile = profiles.factory(profile)
    run: core.Run = profile.init()
    try:
        run.start()
    except BaseException as exc:
        if isinstance(run, core.Run):
            run.abort_start(exc)
        raise
    return run
