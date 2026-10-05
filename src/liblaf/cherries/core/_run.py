# Copyright (c) 2026 liblaf
from __future__ import annotations

import functools
import json
import logging
import math
import os
import shlex
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, SupportsFloat, cast

import attrs
import git
import git.exc
import polars as pl
from environs import env
from slugify import slugify

from liblaf.cherries._capture import capture_environment, capture_source
from liblaf.cherries._settings import load_settings, storage_root
from liblaf.cherries.records import Store
from liblaf.cherries.utils import GitUrlParsed, giturlparse, relative_or_absolute

from .assets import AssetPluginProtocol, AssetsManager
from .metrics import MetricPluginProtocol, MetricsLike, MetricsManager
from .others import OtherPluginProtocol, OthersManager
from .params import ParamPluginProtocol, ParamsManager
from .plugin import PluginManager

if TYPE_CHECKING:
    from _typeshed import StrPath

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@attrs.define
class Run:
    """Mutable state for one Cherries experiment run.

    A `Run` owns plugin registration, path helpers, metrics, parameters, and
    miscellaneous metadata. Profiles configure the process-global run, while
    [`main`][liblaf.cherries.main] starts and ends it around an experiment
    callable.
    """

    def _default_assets(self) -> AssetsManager:
        return AssetsManager(
            working_dir=self.working_dir,
            plugins=cast("AssetPluginProtocol", self.plugins),
        )

    def _default_metrics(self) -> MetricsManager:
        return MetricsManager(plugins=cast("MetricPluginProtocol", self.plugins))

    def _default_others(self) -> OthersManager:
        return OthersManager(plugins=cast("OtherPluginProtocol", self.plugins))

    def _default_params(self) -> ParamsManager:
        return ParamsManager(plugins=cast("ParamPluginProtocol", self.plugins))

    store_root: Path | None = None
    run_id: str = attrs.field(factory=lambda: str(uuid.uuid4()))
    store: Store | None = attrs.field(default=None, repr=False)
    active: bool = False
    record_result: dict[str, Any] | None = None
    _file_handler: logging.Handler | None = attrs.field(default=None, repr=False)
    _source_evidence: dict[str, Any] = attrs.field(factory=dict, repr=False)
    _settings: dict[str, Any] = attrs.field(factory=dict, repr=False)
    _thread_ids: set[int | None] = attrs.field(factory=set, repr=False)
    _child_pids: set[int] = attrs.field(factory=set, repr=False)

    plugins: PluginManager = attrs.field(factory=PluginManager)
    _assets: AssetsManager = attrs.field(
        default=attrs.Factory(_default_assets, takes_self=True),
        repr=False,
        kw_only=True,
    )
    _metrics: MetricsManager = attrs.field(
        default=attrs.Factory(_default_metrics, takes_self=True),
        repr=False,
        kw_only=True,
    )
    _others: OthersManager = attrs.field(
        default=attrs.Factory(_default_others, takes_self=True),
        repr=False,
        kw_only=True,
    )
    _params: ParamsManager = attrs.field(
        default=attrs.Factory(_default_params, takes_self=True),
        repr=False,
        kw_only=True,
    )

    @functools.cached_property
    def entrypoint(self) -> Path:
        """Python entrypoint used to derive the experiment name and folders."""
        if sys.argv[0] == "-c":
            return Path(os.devnull).resolve()
        return Path(sys.argv[0]).resolve()

    @functools.cached_property
    def project_dir(self) -> Path:
        """Git repository root, or the current directory outside a Git repo."""
        if self.repo is None:
            return Path.cwd().resolve()
        return Path(self.repo.working_dir).resolve()

    @functools.cached_property
    def project_name(self) -> str:
        """Project name reported to plugins."""
        if self.repo is None:
            return self.project_dir.name
        try:
            remote: git.Remote = self.repo.remote()
            parsed: GitUrlParsed = giturlparse(remote.url)
        except ValueError:
            return self.project_dir.name
        else:
            return parsed.repo

    @functools.cached_property
    def repo(self) -> git.Repo | None:
        try:
            return git.Repo(search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            logger.warning("%s", exc)

    @functools.cached_property
    def run_key(self) -> Path:
        run_key: Path = relative_or_absolute(self.entrypoint, self.project_dir)
        run_key: Path = _strip_path(run_key)
        run_key: Path = run_key.with_suffix("")
        name: str = self.start_time.strftime("%Y-%m-%dT%H%M%S")
        if custom_name := env.str("CHERRIES_NAME", ""):
            slug: str = slugify(custom_name, lowercase=False, allow_unicode=True)
            name: str = f"{name}-{slug}"
        run_key /= name
        return run_key

    @functools.cached_property
    def run_name(self) -> str:
        """Run name from `CHERRIES_NAME` or the entrypoint path."""
        if name := env.str("CHERRIES_NAME", ""):
            return name
        run_path: Path = relative_or_absolute(self.entrypoint, self.project_dir)
        run_path: Path = _strip_path(run_path)
        run_path: Path = run_path.with_suffix("")
        return run_path.as_posix()

    @functools.cached_property
    def start_time(self) -> datetime:
        """Timezone-aware timestamp captured when the run object is first used."""
        return datetime.now().astimezone()

    @functools.cached_property
    def tags(self) -> list[str]:
        """Tags parsed from the `CHERRIES_TAGS` environment variable."""
        return env.list("CHERRIES_TAGS", [])

    @functools.cached_property
    def working_dir(self) -> Path:
        """Directory used to resolve data, temporary, log, and local snapshot paths."""
        parent: Path = self.entrypoint.parent
        while parent.name in _PATH_SKIP_NAMES:
            parent: Path = parent.parent
        return parent

    # region Lifecycle

    def start(self) -> None:
        """Allocate local work and capture evidence before calling user code."""
        if self.active:
            msg = "a Cherries run is already active"
            raise RuntimeError(msg)
        self.run_id = str(uuid.uuid4())
        self.start_time = datetime.now().astimezone()
        self._settings = load_settings(self.project_dir)
        self.store = Store(self.store_root or storage_root(self.project_dir))
        self.store.ensure_initialized(self._settings.get("collection", {}).get("id"))
        self.working_dir = self.store.start_work(
            self.run_id,
            {
                "pid": os.getpid(),
                "name": self.run_name,
                "machine_id": self.store.machine_id,
            },
        )
        parent = os.environ.get("CHERRIES_PARENT_RUN")
        if parent:
            self.store.register_parent(self.run_id, self.store.resolve_id(parent))
        self._assets = AssetsManager(
            working_dir=self.working_dir,
            plugins=cast("AssetPluginProtocol", self.plugins),
            active=True,
            store=self.store,
            run_id=self.run_id,
        )
        self._metrics = self._default_metrics()
        self._params = self._default_params()
        self._others = self._default_others()
        self.record_result = None
        self.active = True
        logs = self.working_dir / "logs"
        logs.mkdir(parents=True)
        handler = logging.FileHandler(logs / "run.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
        self._file_handler = handler
        self._source_evidence = capture_source(
            self.project_dir,
            self.entrypoint,
            self.working_dir / "source",
            self._settings,
        )
        capture_environment(self.project_dir, self.working_dir / "environment")
        self.plugins.delegate("start")
        self._thread_ids = {thread.ident for thread in threading.enumerate()}
        self._child_pids = self._children()
        self.log_other("cherries/cmd", shlex.join(sys.orig_argv))
        self.log_other(
            "cherries/entrypoint",
            relative_or_absolute(self.entrypoint, self.project_dir),
        )
        self.log_other("cherries/exp_dir", self.working_dir)
        self.log_other("cherries/start_time", self.start_time)
        self.log_other("cherries/run_id", self.run_id)

    def _close_logging(self) -> None:
        if self._file_handler is not None:
            self._file_handler.flush()
            logging.getLogger().removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

    def _join_writers(self) -> None:
        deadline = time.monotonic() + 5
        for thread in threading.enumerate():
            if thread.ident in self._thread_ids:
                continue
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():
                msg = "an experiment thread is still running; work retained"
                raise RuntimeError(msg)
        for pid in self._children() - self._child_pids:
            status = Path(f"/proc/{pid}/status")
            if status.exists() and "State:\tZ" not in status.read_text():
                msg = "an experiment child process is still running; work retained"
                raise RuntimeError(msg)
        writers = self._external_work_writers()
        if writers:
            msg = (
                "an experiment process still has writable work files open; "
                "work retained: " + ", ".join(map(str, sorted(writers)))
            )
            raise RuntimeError(msg)

    @staticmethod
    def _children() -> set[int]:
        path = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
        return (
            {int(value) for value in path.read_text().split()}
            if path.exists()
            else set()
        )

    def _external_work_writers(self) -> set[int]:
        """Return non-run processes with a writable descriptor inside work.

        A process can deliberately or accidentally fork a writer and exit, so
        checking only direct children is insufficient on Linux: the writer is
        reparented before the run reaches its sealing boundary.  ``/proc`` fd
        flags let us conservatively catch writable handles that are open now.
        It cannot prove a process will not open a file later, and it cannot see
        another host or process descriptors the current user may not inspect.
        """
        work = self.working_dir.resolve()
        writers: set[int] = set()
        try:
            processes = tuple(Path("/proc").iterdir())
        except OSError:
            return writers
        for process in processes:
            if not process.name.isdecimal():
                continue
            pid = int(process.name)
            if pid == os.getpid():
                continue
            try:
                if "State:\tZ" in (process / "status").read_text():
                    continue
                descriptors = tuple((process / "fd").iterdir())
            except OSError:
                continue
            for descriptor in descriptors:
                try:
                    target = descriptor.resolve()
                    flags_line = next(
                        line
                        for line in (process / "fdinfo" / descriptor.name)
                        .read_text()
                        .splitlines()
                        if line.startswith("flags:")
                    )
                    flags = int(flags_line.removeprefix("flags:").strip(), 8)
                except (OSError, StopIteration, ValueError):
                    continue
                if target.is_relative_to(work) and flags & os.O_ACCMODE in {
                    os.O_WRONLY,
                    os.O_RDWR,
                }:
                    writers.add(pid)
                    break
        return writers

    def abort_start(self, error: BaseException) -> None:
        """Retain an incomplete stage when source or startup recording fails."""
        self._close_logging()
        if (
            self.store is not None
            and (self.store.root / "pending" / f"{self.run_id}.json").exists()
        ):
            self.store.append_event(
                "recording-incomplete", self.run_id, {"reason": str(error)}
            )
        self._assets.active = False
        self.active = False

    def end(self, exc: BaseException | None = None) -> None:
        """Persist required local evidence; recording failures propagate."""
        if not self.active or self.store is None:
            msg = "no active Cherries run"
            raise RuntimeError(msg)
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            # ``sys.exit(0)`` has the same process outcome as returning from a
            # normal Python experiment.  Seal it before main() re-raises the
            # exception so the interpreter can still exit successfully.
            exc = None
        self.log_other("cherries/end_time", datetime.now().astimezone())
        try:
            self._join_writers()
            if exc is not None:
                diagnostic = "".join(traceback.format_exception(exc))[-65536:]
                self.log_other("cherries/exception", diagnostic)
                self.plugins.delegate("end", exc=exc)
                self._close_logging()
                failure = {
                    "exception": diagnostic,
                    "execution": "failed",
                    "name": self.run_name,
                    "source": self._source_evidence,
                }
                if (
                    self._settings.get("execution", {}).get(
                        "failure_payload", "discard"
                    )
                    == "discard"
                ):
                    self.store.cancel_failed_work(self.run_id, failure)
                else:
                    self.store.append_event("execution-failed", self.run_id, failure)
                return
            self._assets.end()
            end_source = capture_source(
                self.project_dir,
                self.entrypoint,
                self.working_dir / "source-end",
                self._settings,
            )
            stable = self._source_evidence.get("fingerprint") == end_source.get(
                "fingerprint"
            )
            config = self.working_dir / "config"
            config.mkdir(parents=True, exist_ok=True)
            (config / "resolved.json").write_text(
                json.dumps(
                    _json_safe(self.get_params()),
                    default=str,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            )
            (config / "bindings.json").write_text(
                json.dumps(self._assets.bindings, default=str, sort_keys=True, indent=2)
                + "\n"
            )
            metrics = self.get_metrics().to_dicts() if self._metrics.metrics else []
            (self.working_dir / "logs/metrics.json").write_text(
                json.dumps(
                    _json_safe(metrics),
                    default=str,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            )
            (self.working_dir / "RUN.md").write_text(
                f"# {self.run_name}\n\nRun: `{self.run_id}`\n\nExecution: succeeded. Review: unreviewed.\n\nSource stable across execution: {stable}. Replay has not been verified.\n"
            )
            self.plugins.delegate("end", exc=None)
            self._close_logging()
            self.record_result = self.store.seal(
                self.run_id,
                {
                    "kind": "experiment",
                    "name": self.run_name,
                    "tags": self.tags,
                    "command": shlex.join(sys.orig_argv),
                    "argv": sys.argv[1:],
                    "entrypoint": str(
                        relative_or_absolute(self.entrypoint, self.project_dir)
                    ),
                    "execution": {"status": "succeeded", "exit_code": 0},
                    "validation": {"status": "not_evaluated"},
                    "params": _json_safe(self.get_params()),
                    "others": json.loads(
                        json.dumps(
                            _json_safe(self.get_others()), default=str, allow_nan=False
                        )
                    ),
                    "input_bindings": self._assets.bindings,
                    "bundles": self._assets.retained_bundles,
                    "source": self._source_evidence,
                    "source_stability": stable,
                    "replay_verified": False,
                },
                self.working_dir,
            )
            logger.info("Saved Cherries run %s", self.run_id)
        except BaseException as failure:
            self.store.append_event(
                "recording-incomplete",
                self.run_id,
                {"reason": str(failure), "work": str(self.working_dir)},
            )
            raise
        finally:
            self._close_logging()
            self._assets.active = False
            self.active = False

    # endregion Lifecycle

    # region Metrics

    @property
    def step(self) -> int:
        """Default metric step."""
        return self._metrics.step

    @step.setter
    def step(self, value: int) -> None:
        self._metrics.step = value

    def get_step(self) -> int:
        """Return the default metric step."""
        return self.step

    def set_step(self, step: int) -> None:
        """Set the default metric step."""
        self.step = step

    def get_metric(self, name: str) -> pl.DataFrame:
        """Return one metric series."""
        return self._metrics.get_metric(name)

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        """Log one scalar metric."""
        self._metrics.log_metric(name, value, step=step, time=time)

    def get_metrics(self, metrics: Iterator[str] | None = None) -> pl.DataFrame:
        """Return selected metric series concatenated into one dataframe."""
        return self._metrics.get_metrics(metrics)

    def log_metrics(
        self,
        metrics: MetricsLike,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        """Log multiple scalar metrics, flattening nested mappings with `/`."""
        self._metrics.log_metrics(metrics, step=step, time=time)

    # endregion Metrics

    # region Assets

    def input(
        self,
        path: StrPath,
        *,
        name: StrPath | None = None,
        source_run: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Copy verified input bytes into the active run and record their origin."""
        return self._assets.input(
            path, name=name, source_run=source_run, metadata=metadata
        )

    def output(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        """Declare a required output in the active run; missing outputs fail saving."""
        return self._assets.output(path, metadata=metadata, mkdir=mkdir)

    def temp(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        """Return a disposable scratch path in the active run."""
        return self._assets.temp(path, metadata=metadata, mkdir=mkdir)

    def log_asset(
        self,
        path: StrPath,
        metadata: Mapping[str, Any] | None = None,
        *,
        name: StrPath | None = None,
    ) -> Path:
        """Retain an explicit artifact as an independent file inside the active run."""
        return self._assets.log_asset(path, metadata=metadata, name=name)

    def log_input(
        self,
        path: StrPath,
        metadata: Mapping[str, Any] | None = None,
        *,
        name: StrPath | None = None,
    ) -> Path:
        """Copy and retain an existing input in the active run."""
        return self._assets.log_input(path, metadata=metadata, name=name)

    def log_output(
        self,
        path: StrPath,
        metadata: Mapping[str, Any] | None = None,
        *,
        name: StrPath | None = None,
    ) -> Path:
        """Copy or register an existing output inside the active run."""
        return self._assets.log_output(path, metadata=metadata, name=name)

    def log_temp(
        self,
        path: StrPath,
        metadata: Mapping[str, Any] | None = None,
        *,
        name: StrPath | None = None,
    ) -> Path:
        """Promote a temporary file into retained run artifacts."""
        return self._assets.log_temp(path, metadata=metadata, name=name)

    # endregion Assets

    # region Logging

    def get_other(self, name: str) -> Any:
        """Return one flattened metadata value."""
        return self._others.get_other(name)

    def log_other(self, name: str, value: Any) -> None:
        """Log one metadata value."""
        self._others.log_other(name, value)

    def get_others(self) -> dict[str, Any]:
        """Return logged metadata as a nested dictionary."""
        return self._others.get_others()

    def log_others(self, others: Mapping[str, Any]) -> None:
        """Log multiple metadata values."""
        self._others.log_others(others)

    def get_param(self, name: str) -> Any:
        """Return one flattened parameter value."""
        return self._params.get_param(name)

    def log_param(self, name: str, value: Any) -> None:
        """Log one parameter value."""
        self._params.log_param(name, value)

    def get_params(self) -> dict[str, Any]:
        """Return logged parameters as a nested dictionary."""
        return self._params.get_params()

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Log multiple parameter values."""
        self._params.log_params(params)

    # endregion Logging

    def summary(self, prefix: StrPath | None = None) -> dict[str, Any]:
        """Build a JSON/YAML-friendly run summary.

        Args:
            prefix: Optional directory to strip from artifact paths.

        Returns:
            Run metadata, parameters, artifact paths, and user metadata.
        """
        summary: dict[str, Any] = {"name": self.run_name}
        if self.tags:
            summary["tags"] = self.tags
        others: dict[str, Any] = self.get_others()
        summary.update(others.pop("cherries"))
        summary["params"] = self.get_params()
        summary.update(self._assets.summary.to_dict(prefix=prefix))
        summary["others"] = others
        return summary


def _strip_path(path: Path) -> Path:
    return Path(*filter(lambda p: p not in _PATH_SKIP_NAMES, path.parts))
