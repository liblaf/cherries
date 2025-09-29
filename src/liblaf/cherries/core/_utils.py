import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, overload, override

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


class PluginCachedProperty[T](functools.cached_property[T]):
    @overload
    def __get__(self, instance: None, owner: type | None = None) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type | None = None) -> T: ...
    @override
    def __get__(self, instance: object | None, owner: type | None = None) -> Self | T:
        if instance is None:
            return super().__get__(instance, owner)
        if (parent := getattr(instance, "_plugin_parent", None)) is not None:
            instance = parent
        return super().__get__(instance, owner)

    @override
    def __set__(self, instance: object, value: T) -> None:
        assert self.attrname is not None
        instance.__dict__[self.attrname] = value


class PluginProperty[T](property):
    @overload
    def __get__(self, instance: None, owner: type, /) -> Self: ...
    @overload
    def __get__(self, instance: Any, owner: type | None = None, /) -> Any: ...
    def __get__(
        self, instance: object | None, owner: type | None = None, /
    ) -> Self | T:
        if instance is None:
            return super().__get__(instance, owner)
        if (parent := getattr(instance, "_plugin_parent", None)) is not None:
            instance = parent
        return super().__get__(instance, owner)


def plugin_cached_property[T](func: Callable[[Any], T]) -> PluginCachedProperty[T]:
    return PluginCachedProperty(func)


def plugin_property[T](fget: Callable[[Any], T]) -> PluginProperty[T]:
    return PluginProperty(fget)
