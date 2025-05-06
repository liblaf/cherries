import datetime

import attrs
import mlflow

from ._abc import End, LogArtifact, LogArtifacts, LogMetric, LogParam, SetTag, Start


@attrs.define
class Run:
    end: End = attrs.field(factory=End, init=False)
    log_artifact: LogArtifact = attrs.field(factory=LogArtifact, init=False)
    log_artifacts: LogArtifacts = attrs.field(factory=LogArtifacts, init=False)
    log_metric: LogMetric = attrs.field(factory=LogMetric, init=False)
    log_param: LogParam = attrs.field(factory=LogParam, init=False)
    set_tag: SetTag = attrs.field(factory=SetTag, init=False)
    start: Start = attrs.field(factory=Start, init=False)

    @property
    def active_run(self) -> mlflow.ActiveRun:
        return mlflow.active_run()  # pyright: ignore[reportReturnType]

    @property
    def exp_id(self) -> str:
        return self.active_run.info.experiment_id

    @property
    def exp_name(self) -> str:
        return self.exp_id

    @property
    def exp_url(self) -> str:
        tracking_uri: str = self.tracking_uri.rstrip("/")
        return f"{tracking_uri}/#/experiments/{self.exp_id}"

    @property
    def tracking_uri(self) -> str:
        return mlflow.get_tracking_uri()

    @property
    def run_id(self) -> str:
        return self.active_run.info.run_id

    @property
    def run_name(self) -> str:
        return self.active_run.info.run_name  # pyright: ignore[reportReturnType]

    @property
    def run_url(self) -> str:
        return f"{self.exp_url}/runs/{self.run_id}"

    @property
    def start_time(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.active_run.info.start_time / 1000)  # noqa: DTZ006


run = Run()
end: End = run.end
log_artifact: LogArtifact = run.log_artifact
log_artifacts: LogArtifacts = run.log_artifacts
log_metric: LogMetric = run.log_metric
log_param: LogParam = run.log_param
set_tag: SetTag = run.set_tag
start: Start = run.start
