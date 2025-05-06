import functools
from collections.abc import Callable


def cache[**P, T](fn: Callable[P, T]) -> Callable[P, T]:
    return functools.cache(fn)  # pyright: ignore[reportReturnType]
