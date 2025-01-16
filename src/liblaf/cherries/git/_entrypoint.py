import sys
from pathlib import Path

from . import root as git_root


def entrypoint() -> Path:
    fpath: Path = Path(sys.argv[0]).absolute()
    root: Path = git_root()
    if fpath.is_relative_to(root):
        return fpath.relative_to(root)
    return fpath
