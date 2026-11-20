"""The reference delineation case: the buffer it passes on and the summary it prints."""

from types import SimpleNamespace

import pytest

from tools.cases.geographic.reference_catchment_delineation_case import run_case

pytestmark = pytest.mark.fast


def test_main_prints_every_key_of_a_case_summary(monkeypatch, capsys):
    summary = {
        "project_root": "/projects/base",
        "watershed_shp": "watershed.shp",
        "watershed_box_buff_dem": "dem.tif",
        "shape_box_buff_dem": (3, 4),
        "catchment_area_km2": 12.5,
        "mean_elevation_catchment_m": 101.0,
        "figure": None,
    }
    monkeypatch.setattr(
        run_case, "run_geographic_cases_from_toml", lambda *args, **kwargs: {"base": summary}
    )
    assert run_case.main(["--cases", "base", "--no-show-plot"]) == 0
    printed = capsys.readouterr().out
    assert "[base] project_root=/projects/base" in printed
    assert "[base] shape_box_buff_dem=3x4" in printed


@pytest.mark.parametrize(
    ("declared", "passed"), [("20%", "20%"), ("150.0 m", "150.0 m"), (20.0, 20.0), (None, "20%")]
)
def test_the_case_passes_a_declared_buffer_as_it_was_written(declared, passed) -> None:
    """A "20%" or a "150.0 m" is a rule, and float() would read neither."""
    cfg = SimpleNamespace(geographic=SimpleNamespace(snap_dist=50, buff_area=declared))
    specs = run_case.build_case_specs(cfg)
    assert specs["nancon"]["catchment"]["buff_area"] == passed
    assert specs["canut"]["catchment"]["buff_area"] == passed
