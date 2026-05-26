from collections.abc import Generator
from pathlib import Path
from typing import Literal, override

import attrs
import pydantic

from ._abc import Bundle, BundleItem
from ._utils import relative_or_name


def snake_to_kebab(snake: str) -> str:
    """Convert snake_case field names to VTK's kebab-case JSON keys.

    Examples:
        >>> snake_to_kebab("file_series_version")
        'file-series-version'
    """
    return snake.replace("_", "-")


class File(pydantic.BaseModel):
    """One frame entry inside a VTK `.series` file."""

    name: str
    """Frame file name relative to the `.series` file."""

    time: float
    """Frame time value stored by the writer."""


class Series(pydantic.BaseModel):
    """VTK file-series manifest."""

    model_config = pydantic.ConfigDict(alias_generator=snake_to_kebab)
    file_series_version: Literal["1.0"] = "1.0"
    files: list[File] = pydantic.Field(default_factory=list)


@attrs.define
class BundleSeries(Bundle):
    """Bundle a `.series` manifest with every frame it references."""

    @override
    def match(self, path: Path) -> bool:
        """Return whether `path` is a VTK `.series` manifest."""
        return path.suffix == ".series"

    @override
    def ls_files(self, path: Path, prefix: Path) -> Generator[BundleItem]:
        """Yield frame files listed in a VTK `.series` manifest."""
        series: Series = Series.model_validate_json(path.read_bytes())
        for meta in series.files:
            absolute: Path = path.parent / meta.name
            relative: Path = relative_or_name(absolute, prefix)
            yield BundleItem(absolute, relative, optional=False)
