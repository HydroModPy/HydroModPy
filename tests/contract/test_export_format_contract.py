"""Contract tests of the export format port: every served format meets the contract.

Every format registered in :data:`~hydromodpy.results.exporters.registry.export_formats`
declares the members of :class:`~hydromodpy.results.exporters.port.ExportWriter`.
On a copy of a frozen run, each format writes what its declarations state and
returns the list of written paths.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.exporters.port import EXPORT_WRITER_MEMBERS
from hydromodpy.results.exporters.registry import (
    export_formats,
    non_reprojecting_formats,
    one_instant_formats,
)

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_PROJECT = REPO_ROOT / "tests/regression/frozen_runs/v2.0.0/current/projects/example"


def _resolved_formats() -> list[str]:
    """The format names served by the registry in this process."""
    if not export_formats.plugins_loaded:
        export_formats.load_plugins()
    return list(export_formats.names())


@pytest.fixture
def example_project(tmp_path: Path) -> Path:
    """A disposable copy of the frozen example project."""
    project_copy = tmp_path / "example"
    shutil.copytree(FROZEN_PROJECT, project_copy)
    return project_copy


@pytest.mark.parametrize("format_name", _resolved_formats())
def test_every_resolved_format_declares_the_port_contract(format_name: str) -> None:
    """The format defines each member the port requires, with expected types."""
    cls = export_formats.get(format_name)
    for member in EXPORT_WRITER_MEMBERS:
        assert getattr(cls, member, None) is not None, f"{format_name} misses {member}"

    assert cls.name == format_name
    assert cls.suffix.startswith(".")
    assert isinstance(cls.writes, tuple) and len(cls.writes) >= 1
    assert isinstance(cls.natural, tuple)
    assert cls.instants in ("one", "many")
    assert isinstance(cls.reprojects, bool)
    assert isinstance(cls.help, str) and len(cls.help) > 0
    assert callable(getattr(cls, "write", None))


@pytest.mark.parametrize("format_name", _resolved_formats())
def test_format_writes_output_on_frozen_run(format_name: str, example_project: Path) -> None:
    """The format writes its output files and returns their paths."""
    cls = export_formats.get(format_name)
    writer = cls()

    with hmp.open(example_project).store as catalog:
        run = catalog["demo"]
        if "run" in cls.writes:
            written = writer.write(None, None, run.dir)
        elif "field" in cls.writes:
            written = run.export("head", format=format_name, time="last")
        elif "series" in cls.writes:
            written = run.export("discharge", format=format_name, time="last")
        elif "raster" in cls.writes:
            written = run.export("watershed_dem", format=format_name)
        elif "vector" in cls.writes:
            written = run.export("watershed", format=format_name)
        else:
            written = run.export("all", format=format_name)

        assert isinstance(written, list) and len(written) >= 1
        for path in written:
            assert path.is_file(), f"{path} was not created"
            assert path.stat().st_size > 0, f"{path} is empty"
            if "run" not in cls.writes:
                assert path.suffix == cls.suffix, f"{path} does not match {cls.suffix}"


@pytest.mark.parametrize("format_name", _resolved_formats())
def test_format_reprojects_contract(format_name: str) -> None:
    """The format declaration of reprojects matches the derived table."""
    cls = export_formats.get(format_name)
    if "run" in cls.writes:
        return
    if cls.reprojects:
        assert format_name not in non_reprojecting_formats()
    else:
        assert format_name in non_reprojecting_formats()


@pytest.mark.parametrize("format_name", _resolved_formats())
def test_format_instants_contract(format_name: str) -> None:
    """The format declaration of instants matches the derived table."""
    cls = export_formats.get(format_name)
    if "run" in cls.writes:
        return
    if cls.instants == "one":
        assert format_name in one_instant_formats()
    else:
        assert format_name not in one_instant_formats()
