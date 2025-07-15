from typing import Literal

from ._abc import Profile

# ensure profiles are registered
from ._default import ProfileDefault
from ._playground import ProfilePlayground  # noqa: F401

# for code-completion
type ProfileName = Literal["default", "playground"] | str  # noqa: PYI051
type ProfileLike = ProfileName | Profile | type[Profile]


def factory(profile: ProfileLike | None = None) -> Profile:
    if profile is None:
        return ProfileDefault()
    if isinstance(profile, str):
        return Profile[profile]()
    if isinstance(profile, Profile):
        return profile
    return profile()
