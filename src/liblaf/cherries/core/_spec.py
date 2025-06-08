import functools
import inspect
from collections.abc import Callable, Generator, Iterable, Sequence
from typing import Any, Self, overload, override

import attrs
import networkx as nx

from liblaf.grapes.typed import Decorator


def as_seq(value: str | Iterable[str] | None = None) -> Sequence[str]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    return tuple(value)


@attrs.frozen
class SpecDef:
    name: str
    firstresult: bool


@attrs.frozen
class ImplDef:
    name: str
    after: str | Sequence[str] = attrs.field(default=(), converter=as_seq)
    before: str | Sequence[str] = attrs.field(default=(), converter=as_seq)
    priority: int = 0


@attrs.frozen
class ConcreteImpl[C: Callable](ImplDef):
    fn: C = attrs.field(kw_only=True)
    plugin_name: str = attrs.field(kw_only=True)


@attrs.define(slots=False)
class Plugin:
    plugins: list[Self] = attrs.field(factory=list)

    @classmethod
    def get_spec(cls, name: str | SpecDef) -> SpecDef:
        if isinstance(name, SpecDef):
            return name
        fn: Callable | None = getattr(cls, name, None)
        if fn is None:
            raise KeyError(name)
        spec: SpecDef | None = getattr(fn, "spec", None)
        if spec is None:
            raise KeyError(name)
        return spec

    @classmethod
    def iter_specs(cls) -> Generator[SpecDef]:
        for _name, fn in inspect.getmembers(cls):
            spec: SpecDef | None = getattr(fn, "spec", None)
            if spec is None:
                continue
            yield spec

    @property
    def name(self) -> str:
        return type(self).__name__

    @functools.cached_property
    def impls(self) -> dict[str, Sequence[ConcreteImpl]]:
        return {spec.name: tuple(self.iter_impls(spec)) for spec in self.iter_specs()}

    def call(self, spec: str | SpecDef, /, *args, **kwargs) -> Any:
        spec: SpecDef = self.get_spec(spec)
        impls: Sequence[ConcreteImpl] = self.impls.get(spec.name, ())
        if spec.firstresult:
            if len(impls) == 0:
                return None
            return impls[0].fn(*args, **kwargs)
        return [impl.fn(*args, **kwargs) for impl in impls]

    def get_impl(self, spec: str | SpecDef, /) -> ConcreteImpl | None:
        spec: SpecDef = self.get_spec(spec)
        fn: Callable | None = getattr(self, spec.name, None)
        if fn is None:
            return None
        impl: ImplDef | None = getattr(fn, "impl", None)
        if impl is None:
            return None
        return ConcreteImpl(
            name=impl.name,
            after=impl.after,
            before=impl.before,
            priority=impl.priority,
            fn=fn,
            plugin_name=self.name,
        )

    def iter_impls(self, spec: str | SpecDef, /) -> Generator[ConcreteImpl]:
        graph = nx.DiGraph()
        impls: dict[str, ConcreteImpl] = {}
        for impl in self.iter_impls_unordered(spec):
            impls[impl.plugin_name] = impl
            graph.add_node(impl.plugin_name)
            for after in impl.after:
                graph.add_edge(after, impl.plugin_name)
            for before in impl.before:
                graph.add_edge(impl.plugin_name, before)
        for impl in nx.lexicographical_topological_sort(
            graph, key=lambda n: impls[n].priority if n in impls else 0
        ):
            if impl not in impls:
                continue
            yield impls[impl]

    def iter_impls_unordered(self, spec: str | SpecDef, /) -> Generator[ConcreteImpl]:
        spec: SpecDef = self.get_spec(spec)
        for plugin in self.plugins:
            impl: ConcreteImpl | None = plugin.get_impl(spec)
            if impl is None:
                continue
            yield impl

    def register(self, plugin: Self) -> None:
        self.plugins.append(plugin)


@overload
def spec(*, firstresult: bool = False) -> Decorator: ...
@overload
def spec[C: Callable](fn: C, /, *, firstresult: bool = False) -> C: ...
def spec(
    fn: Callable | None = None, /, *, firstresult: bool = False
) -> Decorator | Callable:
    if fn is None:
        return functools.partial(spec, firstresult=firstresult)

    @functools.wraps(fn)
    def wrapper(self: Plugin, *args, **kwargs) -> Any:
        return self.call(wrapper.spec, *args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    wrapper.spec = SpecDef(name=fn.__name__, firstresult=firstresult)  # pyright: ignore[reportAttributeAccessIssue]
    return wrapper


@overload
def impl(
    *,
    name: str,
    after: str | Sequence[str] = (),
    before: str | Sequence[str] = (),
    priority: int = 0,
) -> Decorator: ...
@overload
def impl[C: Callable](
    fn: C,
    /,
    *,
    name: str,
    after: str | Sequence[str] = (),
    before: str | Sequence[str] = (),
    priority: int = 0,
) -> C: ...
def impl(
    fn: Callable | None = None,
    /,
    *,
    name: str,
    after: str | Sequence[str] = (),
    before: str | Sequence[str] = (),
    priority: int = 0,
) -> Decorator | Callable:
    if fn is None:
        return functools.partial(
            impl, name=name, after=after, before=before, priority=priority
        )
    fn.impl = ImplDef(name=name, after=after, before=before, priority=priority)  # pyright: ignore[reportFunctionMemberAccess]
    return override(fn)
