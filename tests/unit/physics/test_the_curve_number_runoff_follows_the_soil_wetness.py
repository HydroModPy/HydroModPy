"""The curve-number runoff reduces to its closed form at the two wetness extremes.

``w = soil_mm / ru_mm`` interpolates the retention between ``S(CN1)`` (dry
soil, AMC I) and ``S(CN3)`` (full soil, AMC III). At each extreme the runoff
is the plain SCS-CN formula with that single retention (HELP eq. 21-24,
Chow, Maidment and Mays 1988, eq. 5.5.6-5.5.7).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import SoilParameters, SoilState, soil_step

_CN = 80.0


def _s1_s3(cn: float) -> tuple[float, float]:
    cn1 = 4.2 * cn / (10.0 - 0.058 * cn)
    cn3 = 23.0 * cn / (10.0 + 0.13 * cn)
    return 25400.0 / cn1 - 254.0, 25400.0 / cn3 - 254.0


def _closed_form(p: float, s: float) -> float:
    ia = 0.2 * s
    excess = p - ia
    return 0.0 if excess <= 0 else excess * excess / (excess + s)


def _params(curve_number: float | None = _CN) -> SoilParameters:
    return SoilParameters(
        ru_mm=np.array([200.0]),
        alpha=1.0,
        kc=0.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=curve_number,
        runoff_time_days=0.0,
    )


def test_a_dry_soil_below_its_retention_threshold_runs_off_nothing() -> None:
    s1, _ = _s1_s3(_CN)
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([0.2 * s1 - 1.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(0.0, abs=1e-12)


def test_a_dry_soil_above_the_threshold_matches_the_closed_form_with_s1() -> None:
    s1, _ = _s1_s3(_CN)
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(_closed_form(50.0, s1), rel=1e-12)


def test_a_full_soil_matches_the_closed_form_with_s3() -> None:
    _, s3 = _s1_s3(_CN)
    ru = 200.0
    state = SoilState(soil_mm=np.array([ru]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(_closed_form(50.0, s3), rel=1e-12)


def test_ru_zero_reads_as_a_full_soil_without_dividing_by_zero() -> None:
    _, s3 = _s1_s3(_CN)
    params = SoilParameters(
        ru_mm=np.array([0.0]),
        alpha=1.0,
        kc=0.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=_CN,
        runoff_time_days=0.0,
    )
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), params)

    assert np.isfinite(day.runoff_cn[0])
    assert day.runoff_cn[0] == pytest.approx(_closed_form(50.0, s3), rel=1e-12)
