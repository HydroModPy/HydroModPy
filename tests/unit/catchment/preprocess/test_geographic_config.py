"""``[geographic]``: its source modes, the DEM conditioning, the engine, the ground corrections
and the retired keys."""

import pytest
from pydantic import ValidationError

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from tests._helpers.geographic_cases import BENCH_RIVER, OUTLET_CATCHMENT, outlet_document

_RETIRED_LAKE_KEYS = (
    "slope",
    "buffer_m",
    "capture_radius_m",
    "capture_max_streams",
    "capture_min_acc_fraction",
)
_ON = {"crossings": {"enabled": True}, "river_network": BENCH_RIVER}
_BED = {"bed_regularization": {"enabled": True}}


def _project_toml(tmp_path, geographic: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        f'[workflow]\nmode = "simulation"\n[workspace]\nroot = "{tmp_path.as_posix()}"\n'
        + geographic,
        encoding="utf-8",
    )
    return HydroModPyConfig.from_toml(path)


def _standard(**overrides: object) -> dict:
    return {"catchment": OUTLET_CATCHMENT, **overrides}


_TXT = {"kind": "txt"}


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        pytest.param(
            {"source_mode": "standard"},
            "geographic.catchment.kind is required when",
            id="standard-without-catch-def",
        ),
        pytest.param(
            {
                "kind": "from_outlet_coord",
                "x_outlet": 1.0,
                "y_outlet": 2.0,
            },
            "Extra inputs are not permitted",
            id="flat-catchment-keys",
        ),
        pytest.param(
            {"catchment": {**_TXT, "cell_size": "150.0 m"}}, "not implemented", id="txt-in-m"
        ),
        pytest.param(
            {"catchment": {**_TXT, "cell_size": "0.15 km"}}, "not implemented", id="txt-in-km"
        ),
        pytest.param({"enforce_streams": {"enabled": True}}, "enforce_streams", id="burn"),
    ],
)
def test_refusals(payload, match) -> None:
    with pytest.raises(ValidationError, match=match):
        GeographicConfig.model_validate(payload)


def test_dem_correction_description() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""
    for words in ("'fill' (default)", "spill level", "'breach'", "Lindsay 2016", "FillDepressions"):
        assert words in description
    assert "recommended" not in description


def test_corrections_off_by_default() -> None:
    config = outlet_document()
    notch, bed = config.crossings, config.bed_regularization
    assert (notch.enabled, notch.path, notch.kinds) == (False, None, ["road", "railway", "bridge"])
    assert (notch.notch_width, notch.bed_reach, notch.max_depth, notch.snap_radius) == (
        10.0,
        50.0,
        3.0,
        30.0,
    )
    assert bed.enabled is False
    assert bed.min_slope == pytest.approx(1.0e-4)


def test_notch_with_a_river_network() -> None:
    assert outlet_document(**_ON).crossings.enabled
    assert outlet_document(crossings={"enabled": False}).crossings.enabled is False
    notch = outlet_document(
        crossings={"notch_width": "20 m", "bed_reach": "0.1 km", "max_depth": "2 m"}
    ).crossings
    assert (notch.notch_width, notch.bed_reach, notch.max_depth) == (20.0, 100.0, 2.0)


@pytest.mark.parametrize(
    ("sections", "match"),
    [
        pytest.param(
            {"crossings": {"enabled": True}}, "river_network", id="notch-without-a-river-network"
        ),
        pytest.param({"crossings": {"kinds": ["weir"]}}, "kinds", id="a-weir-is-not-a-kind"),
        pytest.param({"crossings": {"depth": 3.0}}, "Extra inputs", id="an-unknown-notch-key"),
        pytest.param({"crossings": {"max_depth": 0.0}}, "max_depth", id="a-notch-limit-of-0"),
        pytest.param(
            _BED, r"needs\s+\[geographic.river_network\]", id="bed-without-the-river-network"
        ),
        pytest.param(
            {
                "river_network": BENCH_RIVER,
                "bed_regularization": {"enabled": True, "min_slope": -1},
            },
            "min_slope",
            id="a-negative-bed-slope",
        ),
        pytest.param(
            {"dem_correc_type": "fill", "capped_breach": {"max_depth": 0.8, "max_distance": 100}},
            r"\[geographic.capped_breach\] sets the limits",
            id="capped-breach-limits-without-the-capped-breach",
        ),
    ],
)
def test_correction_refusals(sections, match) -> None:
    with pytest.raises(ValidationError, match=match):
        outlet_document(**sections)


@pytest.mark.parametrize(
    ("build", "sections", "match"),
    [
        pytest.param(GeographicConfig.from_dem, _ON, "kind", id="notch"),
        pytest.param(
            GeographicConfig.from_dem,
            {"river_network": BENCH_RIVER, **_BED},
            "kind = dem",
            id="bed",
        ),
        pytest.param(GeographicConfig.synthetic_case, _ON, "synthetic", id="synthetic"),
    ],
)
def test_correction_without_catchment_refused(build, sections, match) -> None:
    with pytest.raises(ValidationError, match=match):
        build(**sections)
