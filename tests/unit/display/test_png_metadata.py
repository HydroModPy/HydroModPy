"""PNG text chunks that record where a figure came from.

Chunks hold the software, sim_id, field, time, crs_epsg and hydromodpy version.
A figure of a sealed run also gets an identity strip under the image: its label,
its rules and the day.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.display.png_metadata import (
    SOFTWARE_TAG,
    read_png_metadata,
    stamp_png_identity,
    write_png_with_metadata,
)
from hydromodpy.results.identity import read_identity_from
from tests._helpers.run_records import make_identity

pytest.importorskip("PIL")


def test_text_chunks_are_written(tmp_path) -> None:
    values = np.linspace(0.0, 1.0, 64 * 32).reshape(32, 64)

    written = write_png_with_metadata(
        values,
        tmp_path / "head_map.png",
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


def test_extra_chunks_round_trip(tmp_path) -> None:
    out_path = tmp_path / "extras.png"

    write_png_with_metadata(
        np.zeros((4, 4)),
        out_path,
        sim_id="abc",
        extra={"experiment": "calib_2025", "notes": "diagnostic"},
    )

    info = read_png_metadata(out_path)
    assert info["experiment"] == "calib_2025"
    assert info["notes"] == "diagnostic"


def test_stamping_again_replaces_the_strip(tmp_path) -> None:
    from PIL import Image

    sealed = make_identity().labelled("evaluated", label_date=date(2026, 11, 11), rule_version="1")
    out_path = write_png_with_metadata(np.zeros((100, 400)), tmp_path / "map.png")
    stamp_png_identity(out_path, make_identity())
    with Image.open(out_path) as image:
        first = image.size

    stamp_png_identity(out_path, sealed)

    with Image.open(out_path) as image:
        assert image.size == first
    assert read_identity_from(out_path).label == "evaluated"
