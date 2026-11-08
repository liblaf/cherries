# Copyright (c) 2026 liblaf
from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@dataclasses.dataclass
class _CLI:
    repository: Path
    store: Path
    environment: dict[str, str]

    def call(
        self,
        *arguments: str,
        as_json: bool = True,
        expected: int = 0,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "liblaf.cherries.store._cli",
                "--store",
                str(self.store),
                "--project",
                "example",
                *(["--json"] if as_json else []),
                *arguments,
            ],
            cwd=cwd or self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert process.returncode == expected, process.stderr
        return process

    def data(self, *arguments: str, expected: int = 0) -> Any:
        process = self.call(*arguments, expected=expected)
        envelope = json.loads(process.stdout)
        assert envelope["schema_version"] == 1
        assert envelope["command"]
        return envelope["data"]


@pytest.fixture
def cli(tmp_path: Path) -> _CLI:
    repository = tmp_path / "source"
    repository.mkdir()
    for arguments in (
        ["init", "--quiet"],
        ["config", "user.name", "CLI test"],
        ["config", "user.email", "cli@example.invalid"],
    ):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True)
    (repository / "README.md").write_text("# Source\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--quiet", "-m", "initial"],
        check=True,
    )
    home = tmp_path / "home"
    home.mkdir()
    command = _CLI(
        repository,
        tmp_path / "store",
        {
            **os.environ,
            "HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "CHERRIES_STORE": str(tmp_path / "store"),
            "CHERRIES_PROJECT": "example",
            "CHERRIES_COMET": "0",
        },
    )
    command.data("store", "init", str(command.store))
    command.data("project", "add", "example", "--repo", str(repository))
    return command


def _record(cli: _CLI, name: str = "materials", *, tag: str | None = None) -> str:
    options = ["--tag", tag] if tag else []
    run = cli.data("run", "new", "--name", name, "--kind", "dataset", *options)
    cli.data("run", "save", run["id"], "--status", "recorded")
    return run["id"]


def test_cli_prepared_file_report_and_export_workflow(
    cli: _CLI, tmp_path: Path
) -> None:
    assert [item["id"] for item in cli.data("project", "list")] == ["example"]
    assert cli.data("project", "show", "example")["id"] == "example"
    run = cli.data(
        "run",
        "new",
        "--name",
        "measurement",
        "--kind",
        "dataset",
        "--tag",
        "baseline",
        "--parameter",
        "steps=3",
    )
    identifier = run["id"]
    assert Path(run["directory"]).name.endswith(".tmp")
    source = tmp_path / "measurement.vtu"
    source.write_bytes(b"measured mesh")
    cli.data("file", "add", identifier, str(source), "--as", "outputs/measurement.vtu")
    result = cli.data("run", "save", identifier)
    assert result["saved"] is True
    stored = cli.data("run", "show", identifier)
    assert stored["parameters"] == {"steps": 3}
    assert stored["status"] == "recorded"
    directory = Path(stored["directory"])
    assert (directory / "outputs/measurement.vtu.lfs").is_file()
    materialized = cli.call(
        "file", "path", identifier, "outputs/measurement.vtu", as_json=False
    )
    local = Path(materialized.stdout.strip())
    assert local.name == "measurement.vtu"
    assert local.read_bytes() == source.read_bytes()
    copied = tmp_path / "copied.vtu"
    cli.data("file", "get", identifier, "outputs/measurement.vtu", "--to", str(copied))
    assert copied.read_bytes() == source.read_bytes()
    assert "outputs/measurement.vtu" in {
        item["path"] for item in cli.data("file", "list", identifier)
    }
    report = tmp_path / "report.html"
    report.write_text('<html><img src="assets/figure.png"></html>')
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "figure.png").write_bytes(b"figure bytes")
    cli.data(
        "report",
        "add",
        identifier,
        str(report),
        "--as",
        "README.html",
        "--assets",
        str(assets),
    )
    assert (directory / "README.html").read_text() == report.read_text()
    assert (directory / "assets/figure.png").read_bytes() == b"figure bytes"
    exported = tmp_path / "export"
    cli.data("run", "export", identifier, "--to", str(exported), "--with-data")
    assert (exported / "outputs/measurement.vtu").read_bytes() == source.read_bytes()
    cli.data("run", "validate", identifier)
    cli.data("index", "refresh")
    cli.data("index", "rebuild")
    assert cli.data("run", "list", "--tag", "baseline")[0]["id"] == identifier


def test_cli_execution_keeps_stdout_json_and_returns_child_exit(cli: _CLI) -> None:
    program = (
        "import os,sys;from pathlib import Path;"
        "print('child stdout');print('child stderr',file=sys.stderr);"
        "root=Path(os.environ['CHERRIES_RUN_DIR']);"
        "(root/'outputs'/'value.txt').write_text('result');sys.exit(7)"
    )
    process = cli.call(
        "run",
        "exec",
        "--name",
        "failed execution",
        "--",
        sys.executable,
        "-c",
        program,
        expected=7,
    )
    envelope = json.loads(process.stdout)
    assert envelope["data"]["saved"] is True
    assert envelope["data"]["execution_status"] == "failed"
    assert "child stdout" in process.stderr
    assert "child stderr" in process.stderr
    run_id = envelope["data"]["run_id"]
    stored = cli.data("run", "show", run_id)
    assert stored["execution"]["exit_code"] == 7
    assert "child stdout" in (Path(stored["directory"]) / "run.log").read_text()


def test_cli_pins_prepared_inputs_before_execution(cli: _CLI, tmp_path: Path) -> None:
    source_id = _record(cli, "parent")
    source = tmp_path / "mesh.vtu"
    source.write_bytes(b"first mesh")
    cli.data("file", "add", source_id, str(source), "--as", "outputs/mesh.vtu")
    child = cli.data("run", "new", "--name", "child", "--kind", "visualization")
    child_id = child["id"]
    cli.data(
        "file",
        "add",
        child_id,
        "--from-run",
        source_id,
        "--from-project",
        "example",
        "--path",
        "outputs/mesh.vtu",
        "--as",
        "inputs/mesh.vtu",
    )
    assert (Path(child["directory"]) / "inputs/mesh.vtu").read_bytes() == b"first mesh"
    source.write_bytes(b"replacement mesh")
    cli.data("file", "add", source_id, str(source), "--as", "outputs/mesh.vtu")
    program = (
        "import os;from pathlib import Path;"
        "root=Path(os.environ['CHERRIES_RUN_DIR']);"
        "(root/'outputs'/'copy.vtu').write_bytes((root/'inputs'/'mesh.vtu').read_bytes())"
    )
    result = cli.data("run", "exec", child_id, "--", sys.executable, "-c", program)
    assert result["saved"] is True
    materialized = cli.data("file", "path", child_id, "outputs/copy.vtu")
    assert Path(materialized).read_bytes() == b"first mesh"
    stored = cli.data("run", "show", child_id)
    assert stored["sources"][0]["run"] == source_id
    assert stored["input_bindings"][0]["consumed"] is True
    process = cli.call("file", "remove", child_id, "inputs/mesh.vtu", expected=1)
    assert "input" in json.loads(process.stderr)["error"]["message"].lower()


def test_cli_mutable_metadata_edit_and_rejected_execution_change(
    cli: _CLI, tmp_path: Path
) -> None:
    identifier = _record(cli)
    cli.data("run", "tag", "add", identifier, "weekly", "reviewed")
    cli.data("run", "tag", "remove", identifier, "weekly")
    assert cli.data("run", "show", identifier)["tags"] == ["reviewed"]
    editor = tmp_path / "editor.py"
    editor.write_text(
        "import sys,yaml\nfrom pathlib import Path\nprint('editor output')\np=Path(sys.argv[1])\n"
        "d=yaml.safe_load(p.read_text());d['name']='updated name'\n"
        "p.write_text(yaml.safe_dump(d,sort_keys=False))\n"
    )
    cli.environment["EDITOR"] = shlex.join([sys.executable, str(editor)])
    cli.environment.pop("VISUAL", None)
    cli.data("run", "edit", identifier)
    assert cli.data("run", "show", identifier)["name"] == "updated name"
    editor.write_text(
        editor.read_text().replace(
            "d['name']='updated name'", "d['status']='succeeded'"
        )
    )
    process = cli.call("run", "edit", identifier, expected=1)
    assert "editor output" in process.stderr
    assert (
        "fixed execution"
        in json.loads(process.stderr.splitlines()[-1])["error"]["message"]
    )
    assert cli.data("run", "show", identifier)["status"] == "recorded"
    editor.write_text(
        "import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text('# Findings\\n')\n"
    )
    cli.data("report", "edit", identifier, "README.md")
    directory = Path(cli.data("run", "show", identifier)["directory"])
    assert (directory / "README.md").read_text() == "# Findings\n"


def test_cli_missing_html_asset_leaves_published_report_unchanged(
    cli: _CLI, tmp_path: Path
) -> None:
    identifier = _record(cli)
    report = tmp_path / "report.html"
    report.write_text('<img src="assets/missing.png">')
    process = cli.call(
        "report", "add", identifier, str(report), "--as", "README.html", expected=1
    )
    assert (
        "missing local HTML resource" in json.loads(process.stderr)["error"]["message"]
    )
    directory = Path(cli.data("run", "show", identifier)["directory"])
    assert not (directory / "README.html").exists()


def test_cli_nested_html_preserves_stylesheet_asset_topology(
    cli: _CLI, tmp_path: Path
) -> None:
    identifier = _record(cli)
    report = tmp_path / "report.html"
    report.write_text(
        '<link rel="stylesheet" href="assets/theme.css">'
        '<img srcset="data:image/png;base64,AAAA 1x, assets/image.png 2x">'
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "theme.css").write_text("body { background-image: url(image.png) }")
    process = cli.call(
        "report",
        "add",
        identifier,
        str(report),
        "--as",
        "review/details.html",
        "--assets",
        str(assets),
        expected=1,
    )
    assert "image.png" in json.loads(process.stderr)["error"]["message"]
    (assets / "image.png").write_bytes(b"image")
    data = cli.data(
        "report",
        "add",
        identifier,
        str(report),
        "--as",
        "review/details.html",
        "--assets",
        str(assets),
    )
    assert data["report"] == "reports/review/details.html"
    directory = Path(cli.data("run", "show", identifier)["directory"])
    assert (directory / "reports/review/assets/image.png").read_bytes() == b"image"
    assert (directory / "reports/review/assets/theme.css").is_file()


def test_cli_metrics_filter_query_and_export(cli: _CLI, tmp_path: Path) -> None:
    program = (
        "import os,json;from pathlib import Path;"
        "root=Path(os.environ['CHERRIES_RUN_DIR']);"
        "rows=[dict(name='loss',step=i,timestamp_ms=1000,value=v) for i,v in enumerate([1.0,0.001])];"
        "(root/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\\n' for r in rows))"
    )
    result = cli.data(
        "run",
        "exec",
        "--name",
        "metric run",
        "--tag",
        "smile",
        "--",
        sys.executable,
        "-c",
        program,
    )
    identifier = result["run_id"]
    rows = cli.data("metrics", "show", identifier, "--name", "loss")
    assert [row["value"] for row in rows] == [1.0, 0.001]
    queried = cli.data(
        "run",
        "list",
        "--tag",
        "smile",
        "--status",
        "succeeded",
        "--where",
        'metrics["loss"].last < 0.01',
        "--sort=-started_at",
        "--limit",
        "1",
        "--refresh",
    )
    assert [row["id"] for row in queried] == [identifier]
    destination = tmp_path / "metrics.csv"
    cli.data("metrics", "export", identifier, "--to", str(destination))
    assert destination.read_text().splitlines()[0] == "name,step,timestamp_ms,value"


def test_cli_copy_code_checkout_and_dependency_checked_deletion(
    cli: _CLI, tmp_path: Path
) -> None:
    result = cli.data(
        "run", "exec", "--name", "snapshot", "--", sys.executable, "-c", "pass"
    )
    identifier = result["run_id"]
    code = cli.data("code", "show", identifier)
    assert code["git"]["commit"]
    checkout = tmp_path / "checkout"
    cli.data("code", "checkout", identifier, "--to", str(checkout))
    assert (checkout / "README.md").read_text() == "# Source\n"
    cli.data("project", "verify", "example", "--git", "--lfs", "--offline")
    target = tmp_path / "archive"
    cli.data("store", "init", str(target))
    cli.data("run", "copy", identifier, "--to-store", str(target))
    assert (target / "projects/example/runs" / identifier / "run.yaml").is_file()
    cli.data("run", "delete", identifier, "--dry-run")
    assert cli.data("run", "show", identifier)["id"] == identifier
    cli.data("run", "delete", identifier)
    cli.call("run", "show", identifier, expected=1)
    cli.data("store", "gc", "--dry-run")
    cli.data("store", "gc")
    cli.data("store", "verify", "--objects")


def test_cli_context_options_at_command_depth_preserve_child_argv(cli: _CLI) -> None:
    program = "import sys;print(repr(sys.argv[1:]))"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "liblaf.cherries.store._cli",
            "run",
            "exec",
            "--name",
            "arguments",
            "--project",
            "example",
            "--json",
            "--store",
            str(cli.store),
            "--",
            sys.executable,
            "-c",
            program,
            "--store",
            "child-value",
            "--json",
        ],
        cwd=cli.repository,
        env=cli.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["data"]["saved"] is True
    assert "['--store', 'child-value', '--json']" in process.stderr


def test_cli_batch_copy_preflights_conflicts_before_publishing(
    cli: _CLI, tmp_path: Path
) -> None:
    first = _record(cli, "first")
    second = _record(cli, "second")
    target = tmp_path / "target"
    cli.data("store", "init", str(target))
    cli.data("run", "copy", second, "--to-store", str(target))
    target_version = cli.data("run", "show", second, "--store", str(target))[
        "fingerprint"
    ]
    cli.data("run", "tag", "add", second, "reviewed")
    cli.call("run", "copy", first, second, "--to-store", str(target), expected=1)
    assert not (target / "projects/example/runs" / first).exists()
    result = cli.data(
        "run",
        "copy",
        first,
        second,
        "--to-store",
        str(target),
        "--replace",
        "--expect",
        f"example/{second}={target_version}",
    )
    assert result["ok"] is True
    assert (target / "projects/example/runs" / first / "run.yaml").is_file()
    assert cli.data("run", "show", second, "--store", str(target))["tags"] == [
        "reviewed"
    ]


def test_cli_cross_project_selection_checks_and_deletes_dependency_closure(
    cli: _CLI, tmp_path: Path
) -> None:
    parent = _record(cli, "parent", tag="family")
    mesh = tmp_path / "mesh.vtu"
    mesh.write_bytes(b"source mesh")
    cli.data("file", "add", parent, str(mesh), "--as", "outputs/mesh.vtu")
    cli.data("project", "add", "views", "--repo", str(cli.repository))
    child = cli.data(
        "run",
        "new",
        "--name",
        "child",
        "--kind",
        "visualization",
        "--tag",
        "family",
        "--project",
        "views",
    )["id"]
    cli.data(
        "file",
        "add",
        child,
        "--from-run",
        parent,
        "--from-project",
        "example",
        "--path",
        "outputs/mesh.vtu",
        "--as",
        "inputs/mesh.vtu",
        "--project",
        "views",
    )
    cli.data(
        "run", "exec", child, "--project", "views", "--", sys.executable, "-c", "pass"
    )
    process = cli.call("run", "delete", parent, expected=1)
    assert "depend" in json.loads(process.stderr)["error"]["message"].lower()
    rows = cli.data("run", "list", "--all-projects", "--tag", "family")
    assert {row["project"] for row in rows} == {"example", "views"}
    cli.data("run", "delete", "--all-projects", "--tag", "family")
    assert cli.data("run", "list", "--all-projects", "--tag", "family") == []


def test_cli_prepared_metadata_edit_source_relation_and_recovery(
    cli: _CLI, tmp_path: Path
) -> None:
    parent = _record(cli, "source")
    draft = cli.data("run", "new", "--name", "draft", "--source-run", parent)
    identifier = draft["id"]
    cli.data("run", "tag", "add", identifier, "prepared")
    editor = tmp_path / "editor.py"
    editor.write_text(
        "import sys,yaml\nfrom pathlib import Path\np=Path(sys.argv[1])\n"
        "d=yaml.safe_load(p.read_text());d['description']='prepared finding'\n"
        "p.write_text(yaml.safe_dump(d,sort_keys=False))\n"
    )
    cli.environment["EDITOR"] = shlex.join([sys.executable, str(editor)])
    cli.environment.pop("VISUAL", None)
    cli.data("run", "edit", identifier)
    recovered = cli.data("run", "recover", identifier)
    assert str(Path(draft["directory"])) in recovered["retained"]
    cli.data("store", "recover")
    cli.data("run", "save", identifier, "--status", "cancelled")
    stored = cli.data("run", "show", identifier)
    assert stored["description"] == "prepared finding"
    assert stored["parents"] == [{"project": "example", "run": parent}]
    assert stored["status"] == "cancelled"


def test_cli_validation_failure_uses_nonzero_exit_and_version_is_read_only(
    cli: _CLI,
) -> None:
    identifier = _record(cli)
    directory = Path(cli.data("run", "show", identifier)["directory"])
    pointer = directory / "outputs/broken.vtu.lfs"
    pointer.write_text("version https://git-lfs.github.com/spec/v1\nmalformed\n")
    result = cli.data("store", "verify", "--metadata", expected=1)
    assert result["ok"] is False
    assert result["errors"]
    version = cli.call("--version", as_json=False)
    assert version.stdout.strip()


def test_cli_filtered_batch_delete_and_explicit_legacy_format(
    cli: _CLI, tmp_path: Path
) -> None:
    selected = _record(cli, "selected", tag="remove")
    retained = _record(cli, "retained", tag="keep")
    cli.data("run", "delete", "--status", "recorded", "--tag", "remove", "--dry-run")
    cli.data("run", "delete", "--status", "recorded", "--tag", "remove")
    cli.call("run", "show", selected, expected=1)
    assert cli.data("run", "show", retained)["id"] == retained
    cli.call("run", "delete", expected=1)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "collection.json").write_text('{"collection_id":"old"}')
    process = cli.call("project", "list", "--store", str(legacy), expected=1)
    assert "legacy" in json.loads(process.stderr)["error"]["message"].lower()
    assert not (legacy / "store.yaml").exists()
    cli.data("run", "import", str(legacy), "--inspect")


def test_cli_help_and_invalid_command_do_not_create_store(tmp_path: Path) -> None:
    environment = {**os.environ, "CHERRIES_STORE": str(tmp_path / "missing")}
    for arguments, expected in (
        (["--help"], 0),
        (["run", "exec", "--help"], 0),
        (["run", "unknown"], 2),
    ):
        process = subprocess.run(
            [sys.executable, "-m", "liblaf.cherries.store._cli", *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert process.returncode == expected, process.stderr
    assert not (tmp_path / "missing").exists()
