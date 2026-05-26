from __future__ import annotations

import logging
import unittest.mock
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
import comet_ml as comet
import git
import tlz

from liblaf.cherries import core, utils

logger: logging.Logger = logging.getLogger(__name__)


@attrs.frozen
class Asset:
    """Git-tracked asset queued for remote upload at the end of a run."""

    path: Path
    """Local path to the asset."""

    name: Path
    """Asset name inside Comet."""

    metadata: Mapping[str, Any] | None = None
    """Optional Comet asset metadata."""


@attrs.define
class Comet(core.Plugin, core.PluginProtocol):
    """Forward run metadata, metrics, and assets to Comet.

    The plugin starts a Comet experiment with the current project name,
    experiment name, and tags. Git-tracked assets are deferred until the end of
    the run so Comet can receive stable remote URLs after the Git plugin has
    written its final summary or commit.
    """

    disabled: bool = attrs.field(default=False)
    """Start Comet in disabled mode when true."""

    _assets_git: list[Asset] = attrs.field(factory=list)

    @property
    def experiment(self) -> Any:
        """Running Comet experiment or a mock when Comet did not start."""
        return comet.get_running_experiment() or unittest.mock.MagicMock()

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        """Start a Comet experiment for the current Cherries run."""
        try:
            comet.start(
                project_name=self.manager.project_name,
                experiment_config=comet.ExperimentConfig(
                    disabled=self.disabled,
                    name=self.manager.exp_name,
                    tags=self.manager.tags,
                ),
            )
        except ValueError:
            logger.exception("")

    @override
    @core.impl(after=("Git", "Logging"))
    def end(self, *args, **kwargs) -> None:
        """Upload deferred Git assets and end the Comet experiment."""
        try:
            self._log_asset_git_end()
        except git.GitError:
            logger.exception("")
        self.experiment.end()

    @override
    @core.impl
    def get_other(self, name: str) -> Any:
        """Return one Comet `other` value."""
        return self.experiment.get_other(name)

    @override
    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        """Log one Comet `other` value."""
        return self.experiment.log_other(name, value)

    @override
    @core.impl
    def get_others(self) -> Mapping[str, Any]:
        """Return all Comet `other` values."""
        return self.experiment.others

    @override
    @core.impl
    def log_others(self, others: Mapping[str, Any]) -> None:
        """Log multiple Comet `other` values."""
        return self.experiment.log_others(dict(others))

    @override
    @core.impl
    def get_param(self, name: str) -> Any:
        """Return one Comet parameter."""
        return self.experiment.get_parameter(name)

    @override
    @core.impl
    def log_param(self, name: str, value: Any) -> None:
        """Log one Comet parameter."""
        return self.experiment.log_parameter(name, value)

    @override
    @core.impl
    def get_params(self) -> Mapping[str, Any]:
        """Return all Comet parameters."""
        return self.experiment.params

    @override
    @core.impl
    def log_params(self, params: Mapping[str, Any]) -> None:
        """Log multiple Comet parameters."""
        return self.experiment.log_parameters(dict(params))

    @override
    @core.impl
    def get_step(self) -> int | None:
        """Return Comet's current step."""
        return self.experiment.curr_step

    @override
    @core.impl
    def set_step(self, step: int | None = None) -> None:
        """Set Comet's current step."""
        return self.experiment.set_step(step)

    @override
    @core.impl
    def get_url(self) -> str:
        """Return the Comet experiment URL."""
        return self.experiment.url

    @override
    @core.impl
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        """Log one metric to Comet."""
        return self.experiment.log_metric(name, value, step=step)

    @override
    @core.impl
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None:
        """Log multiple metrics to Comet."""
        return self.experiment.log_metrics(dict(metrics), step=step)

    @override
    @core.impl
    def log_asset(
        self,
        path: Path,
        name: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """Log an asset or defer it for Git remote upload."""
        if self._log_asset_git(path, name, metadata=metadata):
            return
        if metadata is not None:
            metadata: dict[str, Any] = dict(metadata)
        self.experiment.log_asset(path, name.as_posix(), metadata=metadata)

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
        """Log an input asset with Comet input metadata."""
        name: Path = Path("inputs") / name
        metadata: dict[str, str] = tlz.assoc(metadata or {}, "type", "input")
        self.log_asset(path, name, metadata=metadata, **kwargs)

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
        """Log an output asset with Comet output metadata."""
        name: Path = Path("outputs") / name
        metadata: dict[str, str] = tlz.assoc(metadata or {}, "type", "output")
        self.log_asset(path, name, metadata=metadata, **kwargs)

    def _log_asset_git(
        self, path: Path, name: Path, *, metadata: Mapping[str, Any] | None = None
    ) -> bool:
        """Queue Git-addressable assets for remote upload."""
        try:
            repo = git.Repo(search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return False
        try:
            repo.git.check_ignore(path)
        except git.GitCommandError as err:
            # Exit code 1 means "not ignored"; paths outside the repository can
            # also fail here, and those should fall back to a normal upload.
            if err.status != 1:
                return False
        else:
            return False
        if repo.working_tree_dir is None:
            return False
        try:
            path.resolve().relative_to(repo.working_tree_dir)
        except ValueError:
            return False
        self._assets_git.append(Asset(path=path, name=name, metadata=metadata))
        return True

    def _log_asset_git_end(self) -> None:
        """Upload queued Git assets as Comet remote assets."""
        if len(self._assets_git) == 0:
            return
        repo = git.Repo(search_parent_directories=True)
        info: utils.GitUrlParsed = utils.giturlparse(repo.remote().url)
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
                    uri: str = f"https://{info.host}/{info.owner}/{info.repo}/raw/{sha}/{relative}"
                case _:
                    uri: str = asset.path.as_posix()
            self.experiment.log_remote_asset(
                uri,
                asset.name.as_posix(),
                metadata=dict(asset.metadata) if asset.metadata is not None else None,
            )
