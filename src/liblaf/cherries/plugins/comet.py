from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
import comet_ml
import cytoolz as toolz

from liblaf import grapes
from liblaf.cherries import core, paths
from liblaf.cherries.typed import PathLike


@attrs.define
class Comet(core.Run):
    disabled: bool = attrs.field(default=False)
    exp: comet_ml.CometExperiment = attrs.field(default=None)

    @override
    @core.impl(after=("Logging",))
    def end(self, *args, **kwargs) -> None:
        return self.exp.end()

    @override
    @core.impl
    def get_others(self) -> Mapping[str, Any]:
        return self.exp.others

    @override
    @core.impl
    def get_params(self) -> Mapping[str, Any]:
        return self.exp.params

    @override
    @core.impl
    def get_url(self) -> str:
        return self.exp.url  # pyright: ignore[reportReturnType]

    @override
    @core.impl(after=("Dvc",))
    def log_asset(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        path = Path(path)
        name = paths.as_posix(name)
        dvc_file: Path = path.with_name(path.name + ".dvc")
        if dvc_file.exists():
            path = dvc_file
            dvc_meta: Mapping[str, Any] = grapes.yaml.load(dvc_file)
            metadata = toolz.merge(metadata or {}, dvc_meta["outs"][0])
        self.exp.log_asset(path, name, metadata=metadata, **kwargs)  # pyright: ignore[reportArgumentType]

    @override
    @core.impl(after=("Dvc",))
    def log_input(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            path = Path(path)
            name = f"inputs/{path.name}"
        metadata = toolz.assoc(metadata or {}, "type", "input")
        self.log_asset(path, name, metadata=metadata, **kwargs)

    @override
    @core.impl
    def log_metric(self, *args, **kwargs) -> None:
        return self.exp.log_metric(*args, **kwargs)

    @override
    @core.impl
    def log_metrics(self, *args, **kwargs) -> None:
        return self.exp.log_metrics(*args, **kwargs)

    @override
    @core.impl
    def log_other(self, *args, **kwargs) -> None:
        return self.exp.log_other(*args, **kwargs)

    @override
    @core.impl
    def log_others(self, *args, **kwargs) -> None:
        return self.exp.log_others(*args, **kwargs)

    @override
    @core.impl(after=("Dvc",))
    def log_output(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            path = Path(path)
            name = f"outputs/{path.name}"
        metadata = toolz.assoc(metadata or {}, "type", "output")
        self.log_asset(path, name, metadata=metadata, **kwargs)

    @override
    @core.impl
    def log_parameter(self, *args, **kwargs) -> None:
        return self.exp.log_parameter(*args, **kwargs)

    @override
    @core.impl
    def log_parameters(self, *args, **kwargs) -> None:
        return self.exp.log_parameters(*args, **kwargs)

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        self.exp = comet_ml.start(
            project_name=self.plugin_root.project_name,
            experiment_config=comet_ml.ExperimentConfig(
                disabled=self.disabled, name=self.plugin_root.name
            ),
        )
