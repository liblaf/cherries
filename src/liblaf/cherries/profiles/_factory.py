from typing import Literal

import environs
from environs import env

from ._abc import Profile

# register profiles
from ._debug import ProfileDebug  # noqa: F401
from ._default import ProfileDefault  # noqa: F401

type ProfileName = Literal["default", "debug"] | str  # noqa: PYI051
"""Registered profile name."""

type ProfileLike = ProfileName | Profile | type[Profile]
"""Profile selector accepted by [`factory`][liblaf.cherries.profiles.factory]."""


def factory(profile: ProfileLike | None = None) -> Profile:
    """Resolve a profile name, instance, class, or environment default.

    Args:
        profile: Explicit profile selector. When omitted, `DEBUG=1` selects the
            debug profile; otherwise `PROFILE` defaults to `default`.

    Returns:
        Instantiated profile object.
    """
    if profile is None:
        try:
            debug: bool = env.bool("DEBUG", False)
        except environs.EnvValidationError:
            pass
        else:
            if debug:
                profile: str = "debug"
    if profile is None:
        profile: str = env.str("PROFILE", "default")
    if isinstance(profile, str):
        return Profile[profile]()
    if isinstance(profile, Profile):
        return profile
    return profile()
