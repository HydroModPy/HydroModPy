"""The capped breach, run for real on Whitebox over a dam across a valley.

A V valley drains south. A dam raised across it at row 20 closes a flat-floored
bowl upstream. The depth of the closed depression is the crest of the dam above
the bowl floor, so one terrain gives a depression the cap may dig (0.3 m), one
it must fill (1 m and 5 m) and, with a three-cell-thick crest, one that only the
length limit refuses.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.terrain import CappedBreach, ConditioningExtent

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("whitebox_workflows")

RES = 25.0
BOWL_FLOOR = 90.5
SIDE_TOLERANCE_M = 0.01
"""The realised lowering follows max_cost within a centimetre (measured, 25 m DEM)."""


@pytest.fixture(autouse=True)
def _single_thread_whitebox(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests._helpers.whitebox import configure_whitebox_single_thread

    configure_whitebox_single_thread(monkeypatch)


@pytest.fixture
def engine():
    from hydromodpy.spatial.terrain import registry

    return registry.create("whitebox_workflows")


def _write(path: Path, surface: np.ndarray) -> Path:
    rows, cols = surface.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=rasterio.transform.from_origin(0.0, rows * RES, RES, RES),
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path


def _dam(tmp_path: Path, *, crest_above_bowl_m: float, thickness: int = 1) -> Path:
    rows, cols = np.mgrid[0:41, 0:31]
    surface = 100.0 - rows * 0.5 + np.abs(cols - 15) * 2.0
    surface[10:20, 10:21] = BOWL_FLOOR
    surface[20 : 20 + thickness, :] = BOWL_FLOOR + crest_above_bowl_m
    return _write(tmp_path / "dam.tif", surface)


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1).astype("float64")


def _condition(engine, dem: Path, tmp_path: Path, method: CappedBreach):
    return engine.condition_dem(
        dem,
        method=method,
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )


def test_a_depression_shallower_than_the_cap_is_dug(engine, tmp_path) -> None:
    dem = _dam(tmp_path, crest_above_bowl_m=0.3)
    result = _condition(engine, dem, tmp_path, CappedBreach(0.5, 200.0))
    diff = _read(result.path) - _read(dem)

    assert result.breach_report.cells_lowered >= 1
    assert result.breach_report.cells_raised == 0
    assert diff.min() == pytest.approx(-0.3, abs=SIDE_TOLERANCE_M)
    assert diff.max() < SIDE_TOLERANCE_M


@pytest.mark.parametrize("crest_above_bowl_m", [1.0, 5.0])
def test_a_depression_deeper_than_the_cap_is_filled_and_not_dug(
    engine, tmp_path, crest_above_bowl_m
) -> None:
    dem = _dam(tmp_path, crest_above_bowl_m=crest_above_bowl_m)
    result = _condition(engine, dem, tmp_path, CappedBreach(0.5, 200.0))
    diff = _read(result.path) - _read(dem)

    assert result.breach_report.cells_lowered == 0
    assert result.breach_report.cells_raised > 1
    assert diff.min() > -SIDE_TOLERANCE_M
    assert diff.max() == pytest.approx(crest_above_bowl_m, abs=SIDE_TOLERANCE_M)


def test_a_breach_longer_than_the_limit_is_filled(engine, tmp_path) -> None:
    """Three cells of crest cost 0.45 m in total: under the depth cap, over the length."""
    dem = _dam(tmp_path, crest_above_bowl_m=0.15, thickness=3)

    long_enough = _condition(engine, dem, tmp_path, CappedBreach(0.5, 200.0))
    too_short = _condition(engine, dem, tmp_path, CappedBreach(0.5, 25.0))

    assert long_enough.breach_report.cells_lowered > 0
    assert long_enough.breach_report.cells_raised == 0
    assert too_short.breach_report.cells_lowered == 0
    assert too_short.breach_report.cells_raised > 0


@pytest.mark.parametrize("crest_above_bowl_m", [0.3, 5.0])
def test_the_report_is_what_the_two_files_say(engine, tmp_path, crest_above_bowl_m) -> None:
    """No cell is lowered by more than the report says, measured here without it.

    The last line holds on this synthetic dam, a single breach path. It is not
    a property of the tool: overlapping paths are costed on the DEM an earlier
    one lowered, so a real DEM can exceed ``max_cost`` (the engine then warns).
    """
    dem = _dam(tmp_path, crest_above_bowl_m=crest_above_bowl_m)
    result = _condition(engine, dem, tmp_path, CappedBreach(0.5, 200.0))
    diff = _read(result.path) - _read(dem)
    report = result.breach_report

    assert report.max_lowering_m == pytest.approx(max(0.0, -diff.min()), abs=1e-9)
    assert report.max_raise_m == pytest.approx(max(0.0, diff.max()), abs=1e-9)
    assert report.cells_lowered == int(np.count_nonzero(diff < -report.move_threshold_m))
    assert report.cells_raised == int(np.count_nonzero(diff > report.move_threshold_m))
    assert float(-diff.min()) <= report.max_lowering_m + 1e-12
    assert report.max_lowering_m <= report.max_cost_m + SIDE_TOLERANCE_M


def test_the_residual_fill_leaves_the_dem_without_a_depression(engine, tmp_path) -> None:
    dem = _dam(tmp_path, crest_above_bowl_m=5.0)
    result = _condition(engine, dem, tmp_path, CappedBreach(0.5, 200.0))
    directions = engine.drainage_directions(result, out=tmp_path / "out" / "pointer.tif")
    codes = _read(directions.path)
    interior = codes[1:-1, 1:-1]

    assert int(np.count_nonzero(interior == 0)) == 0


def test_a_sealed_regional_job_records_the_cap_and_what_it_did(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.schema.job import provenance
    from hydromodpy.schema.job.documents import read_document
    from hydromodpy.spatial.geographic.regional_flow_job import (
        DESCRIPTION_PATH,
        load_regional_flow_job,
        materialize_regional_flow_job,
    )

    monkeypatch.setattr(provenance, "git_state", lambda: {"commit": None, "dirty": None})
    dem = _dam(tmp_path, crest_above_bowl_m=0.3)
    limits = CappedBreach(0.5, 200.0)

    job = materialize_regional_flow_job(
        job_dir=tmp_path / "job",
        dem_init_path=dem,
        dem_correc_type="capped_breach",
        capped_breach=limits,
    )
    description = read_document(Path(job.job_dir) / DESCRIPTION_PATH)
    reread = load_regional_flow_job(
        job_dir=job.job_dir,
        dem_init_path=dem,
        dem_correc_type="capped_breach",
        capped_breach=limits,
    )

    assert description["inputs"]["capped_breach"] == {"max_depth_m": 0.5, "max_distance_m": 200.0}
    assert description["conditioning_report"]["cells_lowered"] >= 1
    assert description["conditioning_report"]["max_dist_cells"] == 8
    assert Path(job.products.correc).name == "dem_capped_breach.tif"
    assert reread.products.accumulation.directions.conditioned_dem.method == limits
    assert reread.job_id == job.job_id
