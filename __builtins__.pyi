# This file is @generated by <https://github.com/liblaf/copier-python>.
# DO NOT EDIT!

# ref: <https://github.com/microsoft/pyright/blob/main/docs/builtins.md>

from typing import overload, type_check_only

@type_check_only
class _IceCreamDebugger:
    @overload
    def __call__(self) -> None: ...
    @overload
    def __call__[T](self, arg: T) -> T: ...
    @overload
    def __call__[T1, T2, *Ts](
        self, arg1: T1, arg2: T2, *args: *Ts
    ) -> tuple[T1, T2, *Ts]: ...

ic: _IceCreamDebugger

__all__ = ["ic"]
