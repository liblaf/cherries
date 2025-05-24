import enum
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pydantic

from liblaf import grapes
from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike


class AssetKind(enum.StrEnum):
    INPUT = enum.auto()
    OUTPUT = enum.auto()


type PathProvider = (
    PathLike | Iterable[PathLike] | Callable[[PathLike], PathLike | Iterable[PathLike]]
)


class MetaAsset:
    kind: AssetKind
    _extra: PathProvider | None = None

    def __init__(self, kind: AssetKind, extra: PathProvider | None = None) -> None:
        self.kind = kind
        self._extra = extra

    def get_extra(self, value: Path) -> list[Path]:
        if self._extra is None:
            return []
        if callable(self._extra):
            extra: Iterable[PathLike] = grapes.as_iterable(self._extra(value))
            return [Path(p) for p in extra]
        extra: Iterable[PathLike] = grapes.as_iterable(self._extra)
        return [Path(p) for p in extra]


def get_assets(cfg: pydantic.BaseModel, kind: AssetKind) -> list[Path]:
    assets: list[Path] = []
    for name, info in type(cfg).model_fields.items():
        value: Any = getattr(cfg, name)
        if isinstance(value, pydantic.BaseModel):
            assets.extend(get_assets(value, kind))
        for meta in info.metadata:
            if isinstance(meta, MetaAsset) and meta.kind == kind:
                value: Path = Path(value)
                assets.append(value)
                assets.extend(meta.get_extra(value))
    return assets


def get_inputs(cfg: pydantic.BaseModel) -> list[Path]:
    return get_assets(cfg, AssetKind.INPUT)


def get_outputs(cfg: pydantic.BaseModel) -> list[Path]:
    return get_assets(cfg, AssetKind.OUTPUT)


def input(path: PathLike, extra: PathProvider | None = None, **kwargs) -> Path:  # noqa: A001
    field_info: pydantic.fields.FieldInfo = pydantic.Field(_path.data(path), **kwargs)  # pyright: ignore[reportAssignmentType]
    field_info.metadata.append(MetaAsset(kind=AssetKind.INPUT, extra=extra))
    return field_info  # pyright: ignore[reportReturnType]


def output(path: PathLike, extra: PathProvider | None = None, **kwargs) -> Path:
    field_info: pydantic.fields.FieldInfo = pydantic.Field(_path.data(path), **kwargs)  # pyright: ignore[reportAssignmentType]
    field_info.metadata.append(MetaAsset(kind=AssetKind.OUTPUT, extra=extra))
    return field_info  # pyright: ignore[reportReturnType]
