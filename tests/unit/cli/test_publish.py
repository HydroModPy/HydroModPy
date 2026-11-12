"""``hmp publish``: copies sealed runs and the summary, and says how to replay the copy.

A copy takes its results and its inputs by default and ``--without`` leaves one
out; ``--with`` goes with ``--package`` only. ``hmp publish .`` leaves a replay
not classed bit out and names it under ``left_out``.
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_OK, EXIT_USAGE
from hydromodpy.results.publication import read_publication, read_published
from tests._helpers.cli_runner import CliRunner
from tests._helpers.published_runs import (
    RUN_NAME,
    make_project,
    make_sealed_run,
    make_summary,
)
from tests._helpers.run_stores import RUN_NAME as DEMO_RUN
from tests._helpers.run_stores import seal_demo_run


def _invoke(*args: str):
    return CliRunner().invoke(["publish", *args])


def test_refused_summary_leaves_no_copy(tmp_path: Path) -> None:
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
    # One sealed run demo, indexed, with its frozen config or without it.
    root = tmp_path / "project"
    run_dir, _ = seal_demo_run(root)
    if config:
        (run_dir / "config.toml").write_text('[site]\nname = "demo"\n', encoding="utf-8")
    return root


def test_copy_says_how_to_replay(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)
    into = tmp_path / "copy"

    result = _invoke(DEMO_RUN, "--to", str(into), "-w", str(project))

    assert result.exit_code == EXIT_OK, result.stderr
    assert read_publication(into).with_ == ["results", "inputs"]
    line = next(text for text in result.stderr.splitlines() if text.startswith("next: "))
    assert shlex.split(line.removeprefix("next: ")) == [
        "hmp",
        "replay",
        str(into.resolve()),
        "-w",
        str(project.resolve()),
    ]
    sealed = json.loads((project / "runs" / DEMO_RUN / "manifest.json").read_text())
    assert f"sealed with HydroModPy {sealed['identity']['hydromodpy_version']}" in result.stderr


def test_no_replay_line_without_config(tmp_path: Path) -> None:
    project = _demo_project(tmp_path, config=False)
    (project / "runs" / DEMO_RUN / "config.toml").unlink(missing_ok=True)

    result = _invoke(
        DEMO_RUN, "--to", str(tmp_path / "copy"), "-w", str(project), "--format", "json",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.stderr
    assert json.loads(result.stdout)["data"]["next"] is None


def test_scratch_product_is_named(tmp_path: Path) -> None:
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

    result = _invoke(DEMO_RUN, "--to", str(tmp_path / "copy"), "-w", str(project))

    assert result.exit_code != EXIT_OK
    assert "a product the run derived in its scratch" in result.stderr
    assert not (tmp_path / "copy").exists()


@pytest.mark.parametrize(
    ("without", "present", "absent"),
    [
        pytest.param("results", {"inputs", "INSTALL.toml"}, {"fields.zarr"}, id="results"),
        pytest.param("inputs", {"fields.zarr"}, {"inputs", "INSTALL.toml"}, id="inputs"),
    ],
)
def test_without(tmp_path: Path, without: str, present: set[str], absent: set[str]) -> None:
    project = _demo_project(tmp_path)
    into = tmp_path / "copy"

    result = _invoke(DEMO_RUN, "--to", str(into), "--without", without, "-w", str(project))

    assert result.exit_code == EXIT_OK, result.stderr
    names = {entry.name for entry in into.iterdir()}
    assert present <= names
    assert not absent & names
    assert without not in read_publication(into).with_
    assert ("next: " in result.stderr) is (without == "results")


COPY_WITH_REFUSAL = (
    "a copy takes its results and its inputs by default. Write --without results or "
    "--without inputs to leave one out; --with goes with --package only."
)
PACKAGE_WITHOUT_REFUSAL = (
    "--without leaves something out of a copy; a package takes what --with names."
)


@pytest.mark.parametrize("extra", ["results", "inputs", "runs"])
def test_with_on_a_copy(tmp_path: Path, extra: str) -> None:
    project = _demo_project(tmp_path)

    result = _invoke(DEMO_RUN, "--to", str(tmp_path / "c"), "--with", extra, "-w", str(project))

    assert result.exit_code == EXIT_USAGE
    assert COPY_WITH_REFUSAL in result.stderr
    assert not (tmp_path / "c").exists()


def test_without_on_a_package(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)

    result = _invoke(
        "--package", "--to", str(tmp_path / "p.tar"), "--without", "inputs", "-w", str(project)
    )

    assert result.exit_code == EXIT_USAGE
    assert PACKAGE_WITHOUT_REFUSAL in result.stderr
    assert not (tmp_path / "p.tar").exists()


def test_package_with(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)

    result = _invoke(
        "--package", "--to", str(tmp_path / "p.tar"), "--with", "runs", "-w", str(project)
    )

    assert result.exit_code == EXIT_OK, result.stderr
    assert (tmp_path / "p.tar").is_file()


def test_copy_and_package_extras(tmp_path: Path) -> None:
    project = _demo_project(tmp_path)

    package = _invoke(
        "--package", "--to", str(tmp_path / "p"), "--with", "inputs", "-w", str(project)
    )
    public = _invoke("--package", "--to", str(tmp_path / "p"), "--public", "-w", str(project))

    assert (package.exit_code, public.exit_code) == (EXIT_USAGE,) * 2
    assert "runs, sessions, mesh, fetched" in package.stderr
    assert "--public" in public.stderr


def test_replay_left_out(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    shutil.copytree(run_dir, project / "runs" / "source")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["lineage"] = {
        **manifest["lineage"],
        "kind": "replay",
        "replay": {"of": "f" * 32, "source": "copy", "source_version": "2.1.0", "basis": "none"},
    }
    manifest["run"]["sim_id"] = "1b2c0000-0000-4000-8000-000000000002"
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    destination = tmp_path / "out"

    result = _invoke(
        ".", "--to", str(destination), "--without", "inputs", "-w", str(project),
        "--format", "json",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.stderr
    data = json.loads(result.stdout)["data"]
    assert [entry["rel_dir"] for entry in data["left_out"]] == [f"runs/{RUN_NAME}"]
    assert "replays a copy that carried no values" in data["left_out"][0]["reason"]
    assert not (destination / RUN_NAME).exists()
    assert (destination / "source").is_dir()
