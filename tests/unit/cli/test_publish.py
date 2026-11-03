"""``hmp publish``: every sealed run and the summary at once, a copy that says how to replay it."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_OK, EXIT_USAGE
from hydromodpy.results.publication import read_publication, read_published
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_run import RUN_NAME as DEMO_RUN
from tests._helpers.sealed_run import seal_demo_run
from tests.unit.results._published_run import (
    RUN_NAME,
    make_project,
    make_sealed_run,
    make_summary,
)


def _invoke(*args: str):
    return CliRunner().invoke(["publish", *args])


def test_the_project_is_published_with_its_summary(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message=f"See {project}/runs/a/mfsim.lst for diagnostics")
    destination = tmp_path / "out"

    result = _invoke(".", "--to", str(destination), "-w", str(project))

    assert result.exit_code == EXIT_OK, result.stderr
    assert {entry.name for entry in destination.iterdir()} == {
        RUN_NAME,
        "summary",
        "PUBLICATION.json",
    }
    assert "runs/a/mfsim.lst" in (destination / "summary" / "by_case.csv").read_text()
    assert "Published 2 copy(ies)" in result.stderr


def test_a_refused_summary_leaves_no_run_copy_behind(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    make_summary(project, error_message="ok", parquet_error=f"{project}/runs/a/mfsim.lst")
    destination = tmp_path / "out" / "bretagne"

    result = _invoke(".", "--to", str(destination), "-w", str(project))

    assert result.exit_code != EXIT_OK
    assert "Nothing was published" in result.stderr
    assert list((tmp_path / "out").iterdir()) == []
    assert read_published(run_dir) == []


def _demo_project(tmp_path: Path, *, config: bool = True) -> Path:
    """A project with one sealed run ``demo``, indexed, with its frozen config or without it."""
    root = tmp_path / "project"
    run_dir, _ = seal_demo_run(root)
    if config:
        (run_dir / "config.toml").write_text('[site]\nname = "demo"\n', encoding="utf-8")
    return root


def test_a_copy_with_its_inputs_says_how_to_run_it_again(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)
    into = tmp_path / "copy"

    result = _invoke(DEMO_RUN, "--to", str(into), "--with", "inputs", "-w", str(project))

    assert result.exit_code == EXIT_OK, result.stderr
    assert read_publication(into).with_ == ["inputs"]
    line = next(text for text in result.stderr.splitlines() if text.startswith("next: "))
    assert shlex.split(line.removeprefix("next: ")) == [
        "hmp",
        "run",
        str(into.resolve() / "config.toml"),
        "--frozen",
        "-w",
        str(project.resolve()),
    ]
    sealed = json.loads((project / "runs" / DEMO_RUN / "manifest.json").read_text())
    assert f"sealed with HydroModPy {sealed['identity']['hydromodpy_version']}" in result.stderr


def test_a_run_without_a_frozen_config_has_no_line_to_replay_it(tmp_path: Path) -> None:
    project = _demo_project(tmp_path, config=False)
    (project / "runs" / DEMO_RUN / "config.toml").unlink(missing_ok=True)

    result = _invoke(
        DEMO_RUN, "--to", str(tmp_path / "copy"), "--with", "inputs", "-w", str(project),
        "--format", "json",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.stderr
    assert json.loads(result.stdout)["data"]["next"] is None


def test_an_input_the_run_derived_in_its_scratch_is_named_as_such(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)
    run_dir = project / "runs" / DEMO_RUN
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    product = tmp_path / "scratch" / "demo.p1" / "_preprocessing" / "hydrography" / "streams.tif"
    inputs["inputs"].append(
        {
            "variable": "hydrography:hydrography_streams",
            "provider": "hydrography",
            "request": {},
            "path": str(product),
            "sha256": "0" * 64,
        }
    )
    (run_dir / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")

    result = _invoke(
        DEMO_RUN, "--to", str(tmp_path / "copy"), "--with", "inputs", "-w", str(project)
    )

    assert result.exit_code != EXIT_OK
    assert "a product the run derived in its scratch" in result.stderr
    assert not (tmp_path / "copy").exists()


def test_the_extras_of_a_copy_and_of_a_package_do_not_mix(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)

    copy = _invoke(DEMO_RUN, "--to", str(tmp_path / "c"), "--with", "runs", "-w", str(project))
    package = _invoke(
        "--package", "--to", str(tmp_path / "p"), "--with", "inputs", "-w", str(project)
    )
    public = _invoke("--package", "--to", str(tmp_path / "p"), "--public", "-w", str(project))

    assert (copy.exit_code, package.exit_code, public.exit_code) == (EXIT_USAGE,) * 3
    assert "results, inputs" in copy.stderr
    assert "runs, sessions, mesh, fetched" in package.stderr
    assert "--public" in public.stderr
