"""``hmp export``: the words of an ``[[export]]`` block, on the command line.

The verb is a thin wrapper of ``hydromodpy.project.api.export``: positionals say what, ``--time``
or ``--period`` when, ``--folder`` or ``--file`` where under
``runs/<run>/exports/``, ``--list`` prints what the run can export,
``--regen`` writes again what ``exports/index.json`` records, and ``--deliver``
sends once more what the ``[[export]]`` blocks of the sealed run name, with no
other word. The three verbs it replaces are gone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.cli.commands.export import _destination
from hydromodpy.cli.output import output_of
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.publication import PublishedLine
from tests._helpers.cli_runner import CliRunner
from tests._helpers.run_stores import RUN_NAME, seal_demo_run


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


def test_an_unknown_as_format_is_refused_with_the_candidates(workspace: Path) -> None:
    result = _invoke("demo", "head", "--time", "last", "--as", "datapackage", "-w", str(workspace))
    assert result.exit_code != 0
    message = result.stderr
    assert "datapackage" in message
    for served in ("csv", "geotiff", "netcdf", "rocrate", "vtu"):
        assert served in message
    assert "hydromodpy.export.format" in message


@pytest.mark.parametrize(
    "words",
    [
        ["head"],
        ["--list"],
        ["--regen"],
        ["--time", "last"],
        ["--period", "2000-02-01", "2000-03-31"],
        ["--as", "csv"],
        ["--to", "maps/"],
        ["--crs", "EPSG:4326"],
        ["--resolution", "10"],
        ["--layer", "0"],
        ["--nodata", "-1"],
    ],
    ids=[
        "variable",
        "list",
        "regen",
        "time",
        "period",
        "as",
        "to",
        "crs",
        "resolution",
        "layer",
        "nodata",
    ],
)
def test_deliver_takes_no_other_word(workspace: Path, words: list[str]) -> None:
    result = _invoke("demo", "--deliver", *words, "-w", str(workspace))

    assert result.exit_code == 2
    assert "--deliver" in result.stderr


def _freeze_config(workspace: Path, extra: str = "") -> None:
    """Write the ``config.toml`` a seal freezes, with no ``[[export]]`` block by default."""
    (workspace / "runs" / RUN_NAME / "config.toml").write_text(
        f"[workspace]\n{extra}", encoding="utf-8"
    )


def test_deliver_without_a_destination_delivers_nothing(workspace: Path) -> None:
    _freeze_config(workspace)

    result = _invoke("demo", "--deliver", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert "Delivered 0 of 0 file(s)" in result.stderr


def test_deliver_json_holds_the_lines_of_the_run(workspace: Path) -> None:
    _freeze_config(workspace)

    result = _invoke("demo", "--deliver", "--format", "json", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema": output_of("export deliver").schema,
        "data": {"deliveries": []},
    }


def test_a_delivered_file_is_listed_and_counted(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = _delivery_line("delivered")
    seen: dict = {}

    def fake_export(run, **kwargs):
        seen.update(kwargs)
        return (line,)

    monkeypatch.setattr("hydromodpy.project.api.export", fake_export)

    result = _invoke("demo", "--deliver", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    assert seen["deliver"] is True
    assert seen["environment"] is not None
    assert result.stdout.splitlines() == [
        "delivered exports/head_last.tif ftp://example.org/incoming/head_last.tif"
    ]
    assert "Delivered 1 of 1 file(s)" in result.stderr


def test_a_failed_delivery_says_the_file_and_leaves_with_one(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = _delivery_line("failed", error="the server did not answer")
    monkeypatch.setattr("hydromodpy.project.api.export", lambda run, **kwargs: (line,))

    result = _invoke("demo", "--deliver", "-w", str(workspace))

    assert result.exit_code == 1
    assert "failed exports/head_last.tif" in result.stdout
    assert "1 of 1 file(s) did not arrive" in result.stderr
    assert "hmp export demo --deliver" in result.stderr


def _delivery_line(state: str, *, error: str | None = None) -> PublishedLine:
    payload = b"head"
    return PublishedLine(
        kind="delivery",
        published_at=datetime(2026, 11, 10, tzinfo=UTC),
        file="exports/head_last.tif",
        destination="ftp://example.org/incoming/head_last.tif",
        state=state,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        attempts=1,
        error=error,
    )


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
