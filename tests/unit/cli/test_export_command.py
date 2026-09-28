"""``hmp export``: the words of an ``[[export]]`` block, on the command line.

The verb is a thin wrapper of ``hmp.export``: positionals say what, ``--time``
or ``--period`` when, ``--folder`` or ``--file`` where, and ``--list`` prints
what the run can export. The three verbs it replaces are gone.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.cli.commands.export import FORMAT_CHOICES
from hydromodpy.core.config_kit.export_spec import ExportFormat
from hydromodpy.core.state.paths import share_dir_for
from hydromodpy.results.catalog import Catalog
from tests._helpers.cli_runner import CliRunner

STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A project holding one monthly run named ``demo`` with a head field and a discharge."""
    root = tmp_path / "project"
    sid = str(uuid.uuid4())
    with Catalog(root) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow6",
            name="demo",
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            crs="EPSG:2154",
            period_start="2000-01-01",
            period_end="2000-04-01",
            time_unit="month",
        )
        if reg.zarr is not None:
            reg.zarr.close()
        x0, y0, step = 385000.0, 6814000.0, 500.0
        verts = np.array(
            [[x0 + i * step, y0 + j * step] for j in range(3) for i in range(3)], dtype="float64"
        )
        conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
        catalog.write_mesh(sid, verts, conn, np.array([50.0, 0.0]))
        catalog.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
        catalog.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
        for t in range(3):
            catalog.write_field(
                sid,
                "head",
                t,
                np.array([[1.0, 2.0, 3.0, 4.0]]) + t,
                n_timesteps=3 if t == 0 else None,
            )
        catalog.write_timeseries(
            sid, "_catchment", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS), unit="m3/s"
        )
    return root


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
    assert not (share_dir_for(workspace) / "demo").exists()


def test_a_field_at_a_date_is_written_and_named(workspace: Path) -> None:
    result = _invoke("demo", "head", "--time", "2000-02-15", "-w", str(workspace))

    assert result.exit_code == 0, result.stderr
    expected = share_dir_for(workspace) / "demo" / "head_2000-02-15.tif"
    assert result.stdout.splitlines() == [str(expected)]
    assert expected.is_file()
    assert "Exported 1 file(s)" in result.stderr


def test_several_times_and_a_format_write_one_file_per_date(workspace: Path) -> None:
    result = _invoke(
        "demo", "head", "--time", "first", "last", "--format", "geopackage", "-w", str(workspace)
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
        "--folder",
        "livrables",
        "-w",
        str(workspace),
    )

    assert result.exit_code == 0, result.stderr
    written = share_dir_for(workspace) / "livrables" / "discharge_2000-02-01_2000-03-31.csv"
    assert result.stdout.strip() == str(written)
    frame = pd.read_csv(written)
    assert frame["datetime"].tolist() == ["2000-03-01 00:00:00", "2000-04-01 00:00:00"]


def test_a_file_with_a_crs_is_reprojected(workspace: Path, tmp_path: Path) -> None:
    import rasterio

    target = tmp_path / "head_wgs84.tif"
    result = _invoke(
        "demo", "head", "--time", "last", "--file", str(target), "--crs", "EPSG:4326",
        "-w", str(workspace),
    )  # fmt: skip

    assert result.exit_code == 0, result.stderr
    with rasterio.open(target) as src:
        assert src.crs.to_epsg() == 4326


def test_nothing_named_is_a_usage_error(workspace: Path) -> None:
    result = _invoke("demo", "-w", str(workspace))

    assert result.exit_code == 2
    assert "--list" in result.stderr


def test_a_name_the_run_does_not_hold_is_refused_with_what_it_holds(workspace: Path) -> None:
    result = _invoke("demo", "watershed", "-w", str(workspace))

    assert result.exit_code == 1
    assert "holds no 'watershed'" in result.stderr
    assert "head" in result.stderr


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
    assert set(FORMAT_CHOICES) == {fmt.value for fmt in ExportFormat}


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
