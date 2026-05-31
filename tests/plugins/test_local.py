from datetime import UTC, datetime
from pathlib import Path

from liblaf.cherries import core
from liblaf.cherries.plugins.local import Local


def test_local_copies_entrypoint_and_assets_into_timestamped_snapshot(
    tmp_path: Path,
) -> None:
    run = core.Run()
    working_dir = tmp_path / "exp" / "demo"
    working_dir.mkdir(parents=True)
    entrypoint = working_dir / "experiment.py"
    entrypoint.write_text("print('hello')\n")
    run.project_dir = tmp_path
    run.working_dir = working_dir
    run.entrypoint = entrypoint
    run.start_time = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    plugin = Local(run=run)
    source_dir = working_dir / "figs"
    source_dir.mkdir()
    (source_dir / "plot.txt").write_text("figure\n")
    output_path = working_dir / "data" / "metrics.json"
    output_path.parent.mkdir()
    output_path.write_text("{}\n")

    plugin.start()
    plugin.log_asset(source_dir)
    plugin.log_asset(output_path, metadata={"type": "output"})

    snapshot = (
        tmp_path / ".cherries" / "runs" / "demo" / "experiment" / "2024-01-02T030405"
    )
    assert (tmp_path / ".cherries" / ".gitignore").read_text() == "*\n"
    assert (snapshot / "src" / "experiment.py").read_text() == "print('hello')\n"
    assert (snapshot / "assets" / "figs" / "plot.txt").read_text() == "figure\n"
    assert (snapshot / "assets" / "data" / "metrics.json").read_text() == "{}\n"
