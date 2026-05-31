from collections.abc import Mapping
from typing import Any


def flatten_dict(
    mapping: Mapping[str, Any], prefix: str = "", sep: str = "/"
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        key_flat: str = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, Mapping):
            result.update(flatten_dict(value, key_flat, sep))
        else:
            result[key_flat] = value
    return result


def unflatten_dict(mapping: Mapping[str, Any], sep: str = "/") -> dict[str, Any]:
    result: dict[str, Any] = {}
    _insert(result, [], mapping, sep=sep)
    return result


def _insert(
    dic: dict[str, Any], path: list[str], value: Any, *, sep: str = "/"
) -> None:
    if len(path) == 0:
        for key, val in value.items():
            _insert(dic, key.split(sep), val, sep=sep)
    else:
        key, *rest = path
        if isinstance(value, Mapping):
            if key not in dic:
                dic[key] = {}
            _insert(dic[key], rest, value, sep=sep)
        else:
            assert len(rest) == 0
            dic[key] = value
