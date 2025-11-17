from typing import Protocol

import giturlparse as _giturlparse


class GitUrlParsed(Protocol):
    """.

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
    info: GitUrlParsed = _giturlparse.parse(url)  # pyright: ignore[reportAssignmentType]
    return info
