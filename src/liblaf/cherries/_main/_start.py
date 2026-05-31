from liblaf.cherries import core, profiles
from liblaf.cherries.profiles import ProfileLike


def start(profile: ProfileLike | None = None) -> core.Run:
    """Create, configure, and start a run from `profile`.

    Args:
        profile: Profile name, instance, class, or `None` for environment-based
            selection.

    Returns:
        Started run.
    """
    profile = profiles.factory(profile)
    run: core.Run = profile.init()
    run.start()
    return run
