from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
import comet_ml
import cytoolz as toolz
import dvc.api
import dvc.exceptions
import git
from loguru import logger

from liblaf import grapes
from liblaf.cherries import core, path_utils
from liblaf.cherries.typing import PathLike


@attrs.frozen
class Asset:
    path: PathLike
    name: PathLike | None
    metadata: Mapping[str, Any] | None = None
    kwargs: Mapping[str, Any] = attrs.field(factory=dict)


@attrs.define
class Comet(core.Run):
    disabled: bool = attrs.field(default=False)
    exp: comet_ml.CometExperiment = attrs.field(default=None)
    _assets_git: list[Asset] = attrs.field(factory=list)

    @override
    @core.impl(after=("Git", "Logging"))
    def end(self, *args, **kwargs) -> None:
        try:
            self._log_asset_git_end()
        except git.GitError as err:
            logger.exception(err)
        self.exp.end()

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
        **kwargs,
    ) -> None:
        if self._log_asset_git(path, name, **kwargs):
            return
        if self._log_asset_dvc(path, name, **kwargs):
            return
        name = path_utils.as_posix(name)
        self.exp.log_asset(path, name, **kwargs)

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
            project_name=self.project_name,
            experiment_config=comet_ml.ExperimentConfig(
                disabled=self.disabled, name=self.exp_name
            ),
        )

    def _log_asset_dvc(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> bool:
        path = Path(path)
        name = path_utils.as_posix(name)
        try:
            # ? I don't know why, but `dvc.api.get_url` only works with this. Maybe a DVC bug?
            dvc_path: Path = path.absolute().relative_to(Path.cwd())
            uri: str = dvc.api.get_url(str(dvc_path))
        except dvc.exceptions.OutputNotFoundError:
            return False
        dvc_file: Path = path.with_name(path.name + ".dvc")
        dvc_meta: Mapping[str, Any] = grapes.yaml.load(dvc_file)
        metadata: dict[str, Mapping] = toolz.merge(metadata or {}, dvc_meta["outs"][0])
        self.exp.log_remote_asset(uri, name, metadata=metadata, **kwargs)
        return True

    def _log_asset_git(
        self,
        path: PathLike,
        name: PathLike | None = None,
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
        info: grapes.git.GitInfo = grapes.git.info()
        for asset in self._assets_git:
            uri: str
            match str(info.platform):
                case "github":
                    path: Path = Path(asset.path).absolute()
                    path_rel: str = path.relative_to(repo.working_tree_dir).as_posix()  # pyright: ignore[reportArgumentType]
                    sha: str = repo.head.commit.hexsha
                    uri = f"https://{info.host}/{info.owner}/{info.repo}/raw/{sha}/{path_rel}"
                case _:
                    uri = path_utils.as_posix(asset.path)
            self.exp.log_remote_asset(
                uri,
                path_utils.as_posix(asset.name),
                metadata=dict(asset.metadata) if asset.metadata is not None else None,
                **asset.kwargs,
            )
