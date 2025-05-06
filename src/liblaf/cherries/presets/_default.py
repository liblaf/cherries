from liblaf.cherries import plugin


def default() -> plugin.Run:
    plugin.run.end.add(
        plugin.LoggingEnd(),
        plugin.GitEnd(),
        plugin.DvcEnd(),
        plugin.MlflowEnd(),
    )
    plugin.run.log_artifact.add(
        plugin.DvcLogArtifact(),
        plugin.MlflowLogArtifact(),
    )
    plugin.run.log_artifacts.add(
        plugin.DvcLogArtifacts(),
        plugin.MlflowLogArtifacts(),
    )
    plugin.run.log_metric.add(
        plugin.MlflowLogMetric(),
    )
    plugin.run.log_param.add(
        plugin.MlflowLogParam(),
    )
    plugin.run.set_tag.add(
        plugin.MlflowSetTag(),
    )
    plugin.run.start.add(
        plugin.LoggingStart(),
        plugin.MlflowStart(),
    )
    return plugin.run
