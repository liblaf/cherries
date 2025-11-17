from liblaf.cherries import core, profiles
from liblaf.cherries.profiles import ProfileLike


def start(profile: ProfileLike | None = None) -> core.Run:
    profile = profiles.factory(profile)
    run: core.Run = profile.init()
    run.start()
    return run
