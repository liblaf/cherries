import logging
import unittest.mock
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
import comet_ml
import cytoolz as toolz
import dvc.api
import dvc.exceptions
import git

from liblaf import grapes
from liblaf.cherries import core, meta

logger: logging.Logger = logging.getLogger(__name__)


@attrs.frozen
class Asset:
    path: Path
    name: Path
    metadata: Mapping[str, Any] | None = None
    kwargs: Mapping[str, Any] = attrs.field(factory=dict)


@attrs.define
class Comet(core.PluginSchema):
    disabled: bool = attrs.field(default=False)
    _assets_git: list[Asset] = attrs.field(factory=list)

    @override
    @core.impl(after=("Git", "Logging"))
    def end(self, *args, **kwargs) -> None:
        try:
            self._log_asset_git_end()
        except git.GitError:
            logger.exception("")
        self.experiment.end()

    @override
    @core.impl
    def get_other(self, name: str) -> Any:
        return self.experiment.get_other(name)

    @override
    @core.impl
    def get_others(self) -> Mapping[str, Any]:
        return self.experiment.others

    @override
    @core.impl
    def get_param(self, name: str) -> Any:
        return self.experiment.get_parameter(name)

    @override
    @core.impl
    def get_params(self) -> Mapping[str, Any]:
        return self.experiment.params

    @override
    @core.impl
    def get_url(self) -> str:
        return self.experiment.url  # pyright: ignore[reportReturnType]

    @override
    @core.impl
    def log_asset(self, path: Path, name: Path, **kwargs) -> None:
        if self._log_asset_git(path, name, **kwargs):
            return
        self.experiment.log_asset(path, name.as_posix(), **kwargs)

    @override
    @core.impl
    def log_input(
        self,
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        name = "inputs" / name
        metadata = toolz.assoc(metadata or {}, "type", "input")
        self.log_asset(path, name, metadata=metadata, **kwargs)

    @override
    @core.impl
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        return self.experiment.log_metric(name, value, step=step, **kwargs)

    @override
    @core.impl
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None:
        return self.experiment.log_metrics(dict(metrics), step=step, **kwargs)

    @override
    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        return self.experiment.log_other(name, value)

    @override
    @core.impl
    def log_others(self, others: Mapping[str, Any]) -> None:
        return self.experiment.log_others(dict(others))

    @override
    @core.impl
    def log_output(
        self,
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        name = "outputs" / name
        metadata = toolz.assoc(metadata or {}, "type", "output")
        self.log_asset(path, name, metadata=metadata, **kwargs)

    @override
    @core.impl
    def log_param(self, name: str, value: Any) -> None:
        return self.experiment.log_parameter(name, value)

    @override
    @core.impl
    def log_params(self, params: Mapping[str, Any]) -> None:
        return self.experiment.log_parameters(dict(params))

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        try:
            comet_ml.start(
                project_name=self.run.project_name,
                experiment_config=comet_ml.ExperimentConfig(
                    disabled=self.disabled, name=self.run.exp_name
                ),
            )
        except ValueError:
            logger.exception("")

    @override
    @core.impl
    def set_step(self, step: int | None = None) -> None:
        return self.experiment.set_step(step)

    @property
    def experiment(self) -> comet_ml.CometExperiment:
        return comet_ml.get_running_experiment() or unittest.mock.MagicMock()

    def _log_asset_dvc(
        self,
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> bool:
        try:
            # ? I don't know why, but `dvc.api.get_url` only works with this. Maybe a DVC bug?
            dvc_path: Path = path.absolute().relative_to(Path.cwd())
            uri: str = dvc.api.get_url(str(dvc_path))
        except dvc.exceptions.OutputNotFoundError:
            return False
        dvc_file: Path = path.with_name(path.name + ".dvc")
        dvc_meta: Mapping[str, Any] = grapes.yaml.load(dvc_file)
        metadata: dict[str, Mapping] = toolz.merge(metadata or {}, dvc_meta["outs"][0])
        self.experiment.log_remote_asset(
            uri, name.as_posix(), metadata=metadata, **kwargs
        )
        return True

    def _log_asset_git(
        self,
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> bool:
        try:
            repo = git.Repo(search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return False
        try:
            if repo.ignored(path):
                return False
        except git.GitCommandError:
            # `path` may be outside repository
            return False
        self._assets_git.append(
            Asset(path=path, name=name, metadata=metadata, kwargs=kwargs)
        )
        return True

    def _log_asset_git_end(self) -> None:
        if len(self._assets_git) == 0:
            return
        repo = git.Repo(search_parent_directories=True)
        info: meta.GitUrlParsed = meta.giturlparse(repo.remote().url)
        for asset in self._assets_git:
            uri: str
            match str(info.platform):
                case "github":
                    assert repo.working_tree_dir is not None
                    absolute: Path = Path(asset.path).absolute()
                    relative: str = absolute.relative_to(
                        repo.working_tree_dir
                    ).as_posix()
                    sha: str = repo.head.commit.hexsha
                    uri = f"https://{info.host}/{info.owner}/{info.repo}/raw/{sha}/{relative}"
                case _:
                    uri = asset.path.as_posix()
            self.experiment.log_remote_asset(
                uri,
                asset.name.as_posix(),
                metadata=dict(asset.metadata) if asset.metadata is not None else None,
                **asset.kwargs,
            )
