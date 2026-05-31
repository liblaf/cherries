from collections.abc import Mapping
from typing import Any


def flatten_dict(
    mapping: Mapping[str, Any], prefix: str = "", sep: str = "/"
) -> dict[str, Any]:
    """Flatten nested mappings into slash-delimited keys.

    Args:
        mapping: Mapping to flatten.
        prefix: Prefix already accumulated by a recursive call.
        sep: Separator inserted between nested key segments.

    Returns:
        A one-level dictionary whose keys preserve the nested path.

    Examples:
        >>> flatten_dict({"train": {"loss": 0.4}, "epoch": 3})
        {'train/loss': 0.4, 'epoch': 3}
    """
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        key_flat: str = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, Mapping):
            result.update(flatten_dict(value, key_flat, sep))
        else:
            result[key_flat] = value
    return result


def unflatten_dict(mapping: Mapping[str, Any], sep: str = "/") -> dict[str, Any]:
    """Expand slash-delimited keys into nested dictionaries.

    Args:
        mapping: Flat mapping to expand.
        sep: Separator used between nested key segments.

    Returns:
        A nested dictionary.

    Examples:
        >>> unflatten_dict({"train/loss": 0.4, "epoch": 3})
        {'train': {'loss': 0.4}, 'epoch': 3}
    """
    result: dict[str, Any] = {}
    _insert(result, [], mapping, sep=sep)
    return result


def _insert(
    dic: dict[str, Any], path: list[str], value: Any, *, sep: str = "/"
) -> None:
    if len(path) == 0:
        for key, val in value.items():
            _insert(dic, key.split(sep), val, sep=sep)
        return

    key, *rest = path
    if len(rest) == 0:
        if isinstance(value, Mapping):
            nested: dict[str, Any] = {}
            _insert(nested, [], value, sep=sep)
            dic[key] = nested
        else:
            dic[key] = value
        return

    child = dic.setdefault(key, {})
    if not isinstance(child, dict):
        child = {}
        dic[key] = child
    _insert(child, rest, value, sep=sep)
