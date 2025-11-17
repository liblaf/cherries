import os
from collections.abc import Generator
from pathlib import Path
from typing import Literal, override

import attrs
import pydantic

from ._abc import Bundle, BundleItem


def snake_to_kebab(snake: str) -> str:
    return snake.replace("_", "-")


class File(pydantic.BaseModel):
    name: str
    time: float


class Series(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(alias_generator=snake_to_kebab)
    file_series_version: Literal["1.0"] = "1.0"
    files: list[File] = []


@attrs.define
class BundleSeries(Bundle):
    @override
    def match(self, path: Path) -> bool:
        return path.suffix == ".series"

    @override
    def ls_files(self, path: Path, prefix: Path) -> Generator[BundleItem]:
        series: Series = Series.model_validate_json(path.read_bytes())
        for meta in series.files:
            absolute: Path = path.parent / meta.name
            relative: str | os.PathLike[str]
            try:
                relative = absolute.relative_to(prefix)
            except ValueError:
                relative = meta.name
            yield BundleItem(absolute, relative, required=True)
