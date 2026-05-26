from typing import Literal

from environs import env

from ._abc import Profile

# ensure profiles are registered
from ._debug import ProfileDebug  # noqa: F401
from ._default import ProfileDefault  # noqa: F401

type ProfileName = Literal["default", "debug"] | str  # noqa: PYI051
type ProfileLike = ProfileName | Profile | type[Profile]


def factory(profile: ProfileLike | None = None) -> Profile:
    """Resolve a profile name, instance, or class to a profile instance.

    If `profile` is omitted, `DEBUG=1` selects the debug profile; otherwise
    `PROFILE` selects a named profile and defaults to `default`.

    Examples:
        >>> factory("debug").__class__.__name__
        'ProfileDebug'
    """
    if profile is None and env.bool("DEBUG", False):
        profile = "debug"
    if profile is None:
        profile: str = env.str("PROFILE", "default")
    if isinstance(profile, str):
        return Profile[profile]()
    if isinstance(profile, Profile):
        return profile
    return profile()
