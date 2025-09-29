import enum
import os
from collections.abc import Callable, Generator, Iterable
from pathlib import Path
from typing import Any, Literal

import attrs
import pydantic

import liblaf.cherries.path_utils as pu
from liblaf import grapes
from liblaf.cherries.typing import PathLike

from ._registry import asset_resolver_registry

type Extra = (
    PathLike
    | Iterable[PathLike]
    | Callable[[PathLike], PathLike | Iterable[PathLike | None] | None]
    | None
)


class AssetKind(enum.StrEnum):
    INPUT = enum.auto()
    OUTPUT = enum.auto()


@attrs.define
class MetaAsset:
    kind: AssetKind
    extra: Extra = None

    def resolve(self, value: Path) -> Generator[Path]:
        if self.extra is None:
            yield from asset_resolver_registry.resolve(value)
            return
        extra: PathLike | Iterable[PathLike | None] | None = (
            self.extra(value) if callable(self.extra) else self.extra  # noqa: S610
        )
        for p in grapes.as_iterable(extra, base_type=(str, bytes, os.PathLike)):
            if p is None:
                continue
            yield Path(p)


def asset(path: PathLike, extra: Extra = None, *, kind: AssetKind, **kwargs) -> Path:
    field_info: pydantic.fields.FieldInfo = pydantic.Field(pu.data(path), **kwargs)  # pyright: ignore[reportAssignmentType]
    field_info.metadata.append(MetaAsset(kind=kind, extra=extra))
    return field_info  # pyright: ignore[reportReturnType]


def get_assets(cfg: pydantic.BaseModel, kind: AssetKind) -> Generator[Path]:
    for name, info in type(cfg).model_fields.items():
        value: Any = getattr(cfg, name)
        if isinstance(value, pydantic.BaseModel):
            yield from get_assets(value, kind)
        for meta in info.metadata:
            if isinstance(meta, MetaAsset) and meta.kind == kind:
                value: Path = Path(value)
                yield value
                yield from meta.resolve(value)


def get_inputs(cfg: pydantic.BaseModel) -> Generator[Path]:
    yield from get_assets(cfg, AssetKind.INPUT)


def get_outputs(cfg: pydantic.BaseModel) -> Generator[Path]:
    yield from get_assets(cfg, AssetKind.OUTPUT)


def input(path: PathLike, extra: Extra = None, **kwargs) -> Path:  # noqa: A001
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


def output(path: PathLike, extra: Extra = None, **kwargs) -> Path:
    return asset(path, extra=extra, kind=AssetKind.OUTPUT, **kwargs)
