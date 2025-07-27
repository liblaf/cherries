from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import wrapt

if TYPE_CHECKING:
    from ._plugin import Plugin


def delegate_property_to_root[C: Callable](func: C) -> C:
    @wrapt.decorator
    def wrapper(
        wrapped: Callable, instance: "Plugin", args: tuple, kwargs: dict[str, Any]
    ) -> None:
        # TODO: make it work with `@functools.cached_property`
        if instance.plugin_root is not instance:
            return wrapped(*args, **kwargs)
        return getattr(instance.plugin_root, wrapped.__name__)

    return func
