from __future__ import annotations

import pydantic_settings as ps

from liblaf import cherries


class Plugin(ps.BaseSettings):
    enabled: bool = True
    priority: float = 0.0

    def pre_start(self) -> None: ...
    def post_start(self, run: cherries.Run) -> None: ...
    def pre_end(self, run: cherries.Run) -> None: ...
    def post_end(self, run: cherries.Run) -> None: ...
