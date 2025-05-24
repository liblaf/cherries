from liblaf.cherries import integration


def default(exp: integration.Experiment) -> integration.Experiment:
    exp.add_tag.add(
        integration.comet.AddTag(),
    )
    exp.add_tags.add(
        integration.comet.AddTags(),
    )
    exp.end.add(
        integration.git.End(),
        integration.dvc.End(),
        integration.logging.End(),
        integration.comet.End(),
    )
    exp.log_asset.add(
        integration.dvc.LogAsset(),
        integration.comet.LogAsset(),
    )
    exp.log_code.add(
        integration.comet.LogCode(),
    )
    exp.log_metric.add(
        integration.comet.LogMetric(),
    )
    exp.log_metrics.add(
        integration.comet.LogMetrics(),
    )
    exp.log_other.add(
        integration.comet.LogOther(),
    )
    exp.log_others.add(
        integration.comet.LogOthers(),
    )
    exp.log_param.add(
        integration.comet.LogParam(),
    )
    exp.log_params.add(
        integration.comet.LogParams(),
    )
    exp.start.add(
        integration.logging.Start(),
        integration.comet.Start(),
    )
    return integration.exp
