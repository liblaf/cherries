from __future__ import annotations

import pydantic_settings as ps

from liblaf import cherries


class Plugin(ps.BaseSettings):
    enabled: bool = True
    priority: float = 0.0

    def pre_start(self) -> None:
        if self.enabled:
            self._pre_start()

    def post_start(self, run: cherries.Run) -> None:
        if self.enabled:
            self._post_start(run)

    def pre_end(self, run: cherries.Run) -> None:
        if self.enabled:
            self._pre_end(run)

    def post_end(self, run: cherries.Run) -> None:
        if self.enabled:
            self._post_end(run)

    def _pre_start(self) -> None: ...
    def _post_start(self, run: cherries.Run) -> None: ...
    def _pre_end(self, run: cherries.Run) -> None: ...
    def _post_end(self, run: cherries.Run) -> None: ...
