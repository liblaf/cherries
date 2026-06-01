from collections.abc import Generator
from pathlib import Path
from typing import ClassVar, Literal, override

import attrs
import pydantic

from ._abc import Bundle, BundleItem


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
    """Parsed VTK `.series` manifest."""

    model_config: ClassVar[pydantic.ConfigDict] = pydantic.ConfigDict(
        alias_generator=snake_to_kebab
    )
    file_series_version: Literal["1.0"] = "1.0"
    """VTK file-series schema version."""

    files: list[File] = pydantic.Field(default_factory=list)
    """Frame entries referenced by the manifest."""


@attrs.define
class BundleSeries(Bundle):
    """Expand a VTK `.series` manifest to its required frame files."""

    @override
    def match(self, path: Path) -> bool:
        """Return whether `path` ends with `.series`."""
        return path.suffix == ".series"

    @override
    def ls_files(self, path: Path) -> Generator[BundleItem]:
        """Read `path` and yield every frame listed in the manifest."""
        series: Series = Series.model_validate_json(path.read_bytes())
        for meta in series.files:
            absolute: Path = path.parent / meta.name
            yield BundleItem(absolute, optional=False)
