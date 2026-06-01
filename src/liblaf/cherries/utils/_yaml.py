import functools
import os
from typing import Any

import msgspec


@functools.singledispatch
def _enc_hook(obj: Any) -> Any:
    return obj


@_enc_hook.register(os.PathLike)
def _(obj: os.PathLike) -> str:
    return os.fsdecode(obj)


def pretty_yaml(data: dict[str, Any]) -> str:
    """Serialize `data` as YAML, converting path-like objects to strings."""
    return msgspec.yaml.encode(data, enc_hook=_enc_hook).decode()
