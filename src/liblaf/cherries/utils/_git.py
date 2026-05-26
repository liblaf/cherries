from typing import Protocol

import giturlparse as _giturlparse


class GitUrlParsed(Protocol):
    """Subset of attributes returned by `giturlparse.parse`.

    References:
        1. <https://github.com/nephila/giturlparse/blob/master/README.rst>
    """

    @property
    def host(self) -> str: ...
    @property
    def platform(self) -> str: ...
    @property
    def owner(self) -> str: ...
    @property
    def repo(self) -> str: ...


def giturlparse(url: str) -> GitUrlParsed:
    """Parse a Git remote URL with the attributes Cherries needs.

    Examples:
        >>> info = giturlparse("https://github.com/liblaf/cherries.git")
        >>> (info.platform, info.owner, info.repo)
        ('github', 'liblaf', 'cherries')
    """
    info: GitUrlParsed = _giturlparse.parse(url)  # pyright: ignore[reportAssignmentType]
    return info
