from liblaf.cherries import integration


def playground(exp: integration.Experiment) -> integration.Experiment:
    exp.end.add(
        integration.logging.End(),
    )
    exp.start.add(
        integration.logging.Start(),
    )
    return integration.exp
