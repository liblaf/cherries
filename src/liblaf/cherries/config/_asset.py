import enum
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import pydantic

from liblaf import grapes
from liblaf.cherries import pathutils
from liblaf.cherries.typing import PathLike


class AssetKind(enum.StrEnum):
    INPUT = enum.auto()
    OUTPUT = enum.auto()


type PathGenerator = (
    PathLike | Iterable[PathLike] | Callable[[PathLike], PathLike | Iterable[PathLike]]
)


path_generators: dict[str, PathGenerator] = {}


def _path_generator_series(path: PathLike) -> list[Path]:
    path = Path(path)
    if (folder := path.with_suffix(".d")).exists():
        return [folder]
    if (folder := path.with_suffix("")).exists():
        return [folder]
    return []


path_generators[".series"] = _path_generator_series


class MetaAsset:
    kind: AssetKind
    _extra: PathGenerator | None = None

    def __init__(self, kind: AssetKind, extra: PathGenerator | None = None) -> None:
        self.kind = kind
        self._extra = extra

    def get_extra(self, value: Path) -> list[Path]:
        extra: PathGenerator | None = self._extra
        if extra is None:
            extra = path_generators.get(value.suffix)
        if extra is None:
            return []
        if callable(extra):
            extra = extra(value)
        extra = grapes.as_iterable(extra)
        return [Path(p) for p in extra]


def asset(
    path: PathLike, extra: PathGenerator | None = None, *, kind: AssetKind, **kwargs
) -> Path:
    field_info: pydantic.fields.FieldInfo = pydantic.Field(
        pathutils.data(path), **kwargs
    )  # pyright: ignore[reportAssignmentType]
    field_info.metadata.append(MetaAsset(kind=kind, extra=extra))
    return field_info  # pyright: ignore[reportReturnType]


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


def input(path: PathLike, extra: PathGenerator | None = None, **kwargs) -> Path:  # noqa: A001
    return asset(path, extra=extra, kind=AssetKind.INPUT, **kwargs)


def model_dump_without_assets(
    model: pydantic.BaseModel,
    *,
    mode: str | Literal["json", "python"] = "json",  # noqa: PYI051
    **kwargs,
) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode=mode, **kwargs)
    for name, info in type(model).model_fields.items():
        value: Any = getattr(model, name)
        if isinstance(value, pydantic.BaseModel):
            value = model_dump_without_assets(value)
        for meta in info.metadata:
            if isinstance(meta, MetaAsset):
                del data[name]
                break
        else:
            data[name] = value
    return data


def output(path: PathLike, extra: PathGenerator | None = None, **kwargs) -> Path:
    return asset(path, extra=extra, kind=AssetKind.OUTPUT, **kwargs)
