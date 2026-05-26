from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from liblaf.cherries.plugins.local import Local


def test_local_copies_assets_into_timestamped_snapshot(tmp_path: Path) -> None:
    entrypoint = tmp_path / "experiment.py"
    entrypoint.write_text("print('hello')\n")
    manager = SimpleNamespace(
        entrypoint=entrypoint,
        exp_dir=tmp_path,
        start_time=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    plugin = Local()
    plugin.manager = manager
    source_dir = tmp_path / "figs"
    source_dir.mkdir()
    (source_dir / "plot.txt").write_text("figure\n")
    input_path = tmp_path / "data" / "raw.csv"
    input_path.parent.mkdir()
    input_path.write_text("raw\n")
    output_path = tmp_path / "data" / "metrics.json"
    output_path.write_text("{}\n")
    temp_path = tmp_path / "temp" / "scratch.txt"
    temp_path.parent.mkdir()
    temp_path.write_text("scratch\n")

    plugin.log_asset(source_dir, Path("figs"))
    plugin.log_input(input_path, Path("raw.csv"))
    plugin.log_output(output_path, Path("metrics.json"))
    plugin.log_temp(temp_path, Path("scratch.txt"))

    snapshot = tmp_path / ".cherries" / "experiment" / "2024-01-02T030405"
    assert (tmp_path / ".cherries" / ".gitignore").read_text() == "*\n"
    assert (snapshot / "figs" / "plot.txt").read_text() == "figure\n"
    assert (snapshot / "inputs" / "raw.csv").read_text() == "raw\n"
    assert (snapshot / "outputs" / "metrics.json").read_text() == "{}\n"
    assert (snapshot / "tmp" / "scratch.txt").read_text() == "scratch\n"
