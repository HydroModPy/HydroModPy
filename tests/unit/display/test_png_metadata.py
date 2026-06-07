"""Unit tests for PNG metadata embedding.

Covers ``hydromodpy.display.png_metadata``:
- tEXt chunks for software, sim_id, field, time, crs_epsg, hmp_version
- read/write round trip
- matplotlib figure and numpy array inputs
- missing optional fields are silently dropped
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.display.png_metadata import (
    SOFTWARE_TAG,
    read_png_metadata,
    write_png_with_metadata,
)


def test_png_text_chunks_present(tmp_path) -> None:
    pytest.importorskip("PIL")

    arr = np.linspace(0.0, 1.0, 64 * 32).reshape(32, 64)
    out_path = tmp_path / "head_map.png"
    written = write_png_with_metadata(
        arr,
        out_path,
        sim_id="sim_abc123",
        field="head",
        time="2020-01-15T00:00:00",
        crs_epsg=2154,
    )
    assert written.exists()
    info = read_png_metadata(written)
    assert info["sim_id"] == "sim_abc123"
    assert info["field"] == "head"
    assert info["time"] == "2020-01-15T00:00:00"
    assert info["crs_epsg"] == "2154"
    assert info["software"] == SOFTWARE_TAG
    assert info["hmp_version"] == str(HMP_VERSION)


def test_png_metadata_includes_sim_provenance(tmp_path) -> None:
    pytest.importorskip("PIL")

    arr = np.zeros((8, 8))
    out_path = tmp_path / "blank.png"
    write_png_with_metadata(arr, out_path, sim_id="run_xyz", field="recharge")
    info = read_png_metadata(out_path)
    assert info["sim_id"] == "run_xyz"
    assert info["field"] == "recharge"
    assert info["software"].startswith("HydroModPy")


def test_png_metadata_optional_fields_dropped(tmp_path) -> None:
    pytest.importorskip("PIL")

    arr = np.ones((16, 16))
    out_path = tmp_path / "ones.png"
    write_png_with_metadata(arr, out_path)
    info = read_png_metadata(out_path)
    assert "sim_id" not in info
    assert "field" not in info
    assert info["software"] == SOFTWARE_TAG


def test_png_metadata_with_matplotlib_figure(tmp_path) -> None:
    pytest.importorskip("PIL")
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    out_path = tmp_path / "lineplot.png"
    write_png_with_metadata(
        fig,
        out_path,
        sim_id="figsim",
        field="head",
        time="2024",
        crs_epsg=3857,
    )
    plt.close(fig)
    info = read_png_metadata(out_path)
    # matplotlib's metadata= kwarg writes tEXt chunks via the PNG plugin.
    assert info["sim_id"] == "figsim"
    assert info["crs_epsg"] == "3857"


def test_png_extra_chunks_round_trip(tmp_path) -> None:
    pytest.importorskip("PIL")

    arr = np.zeros((4, 4))
    out_path = tmp_path / "extras.png"
    write_png_with_metadata(
        arr,
        out_path,
        sim_id="abc",
        extra={"experiment": "calib_2025", "notes": "diagnostic"},
    )
    info = read_png_metadata(out_path)
    assert info["experiment"] == "calib_2025"
    assert info["notes"] == "diagnostic"
