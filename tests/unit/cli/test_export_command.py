"""``hmp export``: the words of an ``[[export]]`` block, on the command line.

The verb is a thin wrapper of ``hmp.export``: positionals say what, ``--time``
or ``--period`` when, ``--folder`` or ``--file`` where under
``runs/<run>/exports/``, ``--list`` prints what the run can export and
``--regen`` writes again what ``exports/index.json`` records. The three verbs
it replaces are gone.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.cli.commands.export import FILE_FORMATS, _destination
from hydromodpy.results.exporters.export_spec import ExportFormat
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_run import RUN_NAME, seal_demo_run


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A project holding one sealed monthly run named ``demo``, indexed."""
    project = tmp_path / "project"
    seal_demo_run(project)
    return project


def _exports(workspace: Path) -> Path:
    return workspace / "runs" / RUN_NAME / "exports"


def _invoke(*args: str):
    return CliRunner().invoke(["export", *args])


def test_the_list_prints_what_the_run_can_export_by_kind(workspace: Path) -> None:
    result = _invoke("demo", "--list", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "demo can export:"
    assert "fields:" in lines
    assert "  head" in lines
    assert "series:" in lines
    assert "  discharge" in lines
    assert lines.index("fields:") < lines.index("series:")
    assert not _exports(workspace).exists()


def test_a_field_at_a_date_is_written_and_named(workspace: Path) -> None:
    result = _invoke("demo", "head", "--time", "2000-02-15", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    expected = _exports(workspace) / "head_2000-02-15.tif"
    assert result.stdout.splitlines() == [str(expected)]
    assert expected.is_file()
    assert "Exported 1 file(s)" in result.stderr
    assert read_identity_from(expected).case_id == RUN_NAME
    assert [entry.file for entry in Ledger.read(_exports(workspace)).entries] == [
        "head_2000-02-15.tif"
    ]


def test_several_times_and_a_format_write_one_file_per_date(workspace: Path) -> None:
    result = _invoke(
        "demo", "head", "--time", "first", "last", "--as", "geopackage", "-w", str(workspace)
    )

    assert result.exit_code == 0, result.stderr
    assert sorted(Path(line).name for line in result.stdout.splitlines()) == [
        "head_first.gpkg",
        "head_last.gpkg",
    ]


def test_a_period_and_a_folder_are_honoured(workspace: Path) -> None:
    result = _invoke(
        "demo",
        "discharge",
        "--period",
        "2000-02-01",
        "2000-03-31",
        "--to",
        "livrables",
        "-w",
        str(workspace),
    )

    assert result.exit_code == 0, result.stderr
    written = _exports(workspace) / "livrables" / "discharge_2000-02-01_2000-03-31.csv"
    assert result.stdout.strip() == str(written)
    frame = pd.read_csv(written)
    assert frame["datetime"].tolist() == ["2000-03-01 00:00:00", "2000-04-01 00:00:00"]


def test_a_file_with_a_crs_is_reprojected(workspace: Path) -> None:
    import rasterio

    result = _invoke(
        "demo", "head", "--time", "last", "--to", "head_wgs84.tif", "--crs", "EPSG:4326",
        "-w", str(workspace),
    )  # fmt: skip

    assert result.exit_code == 0, result.stderr
    with rasterio.open(_exports(workspace) / "head_wgs84.tif") as src:
        assert src.crs.to_epsg() == 4326


def test_an_absolute_file_is_refused_with_hmp_publish(workspace: Path, tmp_path: Path) -> None:
    result = _invoke(
        "demo", "head", "--time", "last", "--to", str(tmp_path / "h.tif"), "-w", str(workspace),
    )  # fmt: skip

    assert result.exit_code != 0
    assert "hmp publish" in result.stderr
    assert not (tmp_path / "h.tif").exists()


def test_regen_writes_again_what_the_ledger_records(workspace: Path) -> None:
    first = _invoke("demo", "head", "--time", "last", "-w", str(workspace))
    assert first.exit_code == 0, first.stderr
    written = _exports(workspace) / "head_last.tif"
    written.unlink()

    result = _invoke("demo", "--regen", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines() == [str(written)]
    assert written.is_file()


def test_regen_names_the_ledger_and_says_when_it_records_nothing(workspace: Path) -> None:
    assert _invoke("demo", "--regen", "-w", str(workspace)).exit_code != 0
    assert "no export and no figure" in _invoke("demo", "--regen", "-w", str(workspace)).stderr
    assert "records no figure" in _invoke("demo", "--regen", "figures", "-w", str(workspace)).stderr


@pytest.mark.parametrize(
    ("to", "expected"),
    [
        (None, (None, None)),
        ("maps", ("maps", None)),
        ("maps/", ("maps/", None)),
        ("maps/watertable.tif", (None, "maps/watertable.tif")),
    ],
)
def test_to_is_a_file_when_it_has_an_extension(to, expected) -> None:
    assert _destination(to) == expected


def test_nothing_named_is_a_usage_error(workspace: Path) -> None:
    result = _invoke("demo", "-w", str(workspace))

    assert result.exit_code == 2
    assert "--list" in result.stderr


def test_a_name_the_run_does_not_hold_is_refused_with_what_it_holds(workspace: Path) -> None:
    result = _invoke("demo", "watershed_contour", "-w", str(workspace))

    assert result.exit_code == 1
    assert "holds no 'watershed_contour'" in result.stderr
    assert "head" in result.stderr
    assert not _exports(workspace).exists()


def test_the_layers_a_run_holds_are_read_from_its_directory(workspace: Path) -> None:
    """The index is not asked: a layer whose file is gone is not held any more."""
    tables = workspace / "runs" / RUN_NAME / "tables.parquet"
    (tables / "geographic_watershed.parquet").unlink()

    result = _invoke("demo", "watershed", "-w", str(workspace))

    assert result.exit_code == 1
    assert "holds no 'watershed'" in result.stderr


def test_an_unknown_run_is_not_found(workspace: Path) -> None:
    result = _invoke("nosuchrun", "head", "-w", str(workspace))

    assert result.exit_code == 10


def test_a_request_the_model_refuses_is_refused_before_writing(workspace: Path) -> None:
    result = _invoke(
        "demo", "head", "--time", "last", "--period", "2000-01-01", "2000-02-01",
        "-w", str(workspace),
    )  # fmt: skip

    assert result.exit_code != 0
    assert "time and period are both given" in result.stderr


def test_the_format_choices_are_the_export_formats() -> None:
    assert set(FILE_FORMATS) == {fmt.value for fmt in ExportFormat}


@pytest.mark.parametrize(
    "argv",
    [
        ["data", "export", ".", "--list"],
        ["data", "export-package", "x", "-o", "x.hmp"],
        ["catalog", "export", "x"],
    ],
)
def test_the_verbs_hmp_export_replaces_are_gone(argv: list[str]) -> None:
    assert CliRunner().invoke(argv).exit_code == 2
