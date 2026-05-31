from liblaf.cherries.utils import flatten_dict, unflatten_dict


def test_flatten_and_unflatten_round_trip_slash_delimited_keys() -> None:
    nested = {"train": {"loss": 0.4, "accuracy": 0.9}, "epoch": 3}

    flat = flatten_dict(nested)

    assert flat == {"train/loss": 0.4, "train/accuracy": 0.9, "epoch": 3}
    assert unflatten_dict(flat) == nested
