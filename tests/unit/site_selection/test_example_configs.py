"""Config-parse checks for the shipped site-selection example configs.

Only the fast, config-parse-only examples live here (one test per config,
parametrized). The slower examples that exercise the full workflow run were
moved to ``tests/integration/site_selection/test_site_selection_example_runs.py``
(see git history) and are intentionally not covered by this file: discovering
every ``*.toml`` under the example directory here would silently re-absorb
those integration-tier and probe configs into the unit tier.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.workflow.site_selection import (
    load_data_dem_config_for_site_selection,
    load_hydrometry_config_for_site_selection,
    load_site_selection_config,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "17_site_selection_workflow"


def _check_bretagne_hydrometry_primary(site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any) -> None:
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.strategy.primary_observation_type == "flow_station"
    assert site_cfg.input.mode == "delineated_catchments"
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].product == "QmnJ"


def _check_bretagne_hydrometry_hubeau_preview(
    site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any
) -> None:
    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.territory.regions == ["Bretagne"]
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(500.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].product == "QmnJ"
    assert hydrometry_cfg.sources[0].extent == "study_area"


def _check_auvergne_rhone_alpes_hydrometry(
    site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any
) -> None:
    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.territory.regions == ["Auvergne-Rhone-Alpes"]
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(150.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Auvergne-Rhone-Alpes"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"


def _check_auvergne_rhone_alpes_hydrometry_preview(
    site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any
) -> None:
    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.strategy.principle == "observation_led"
    assert site_cfg.selection_id == "aura_hydrometry_preview_v1"
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Auvergne-Rhone-Alpes"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].station_ids == [
        "K003002010",
        "K004551001",
        "K010002010",
        "K013401001",
        "K021401001",
    ]


def _check_bretagne_hydrometry_small(site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any) -> None:
    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.criteria.area.ranges[0].min_area_km2 == pytest.approx(50.0)
    assert site_cfg.criteria.area.ranges[0].max_area_km2 == pytest.approx(500.0)
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Bretagne"]
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"
    assert hydrometry_cfg.sources[0].station_ids == [
        "J061161001",
        "J062661001",
        "J110301001",
        "J111401001",
        "J131301001",
        "J132401001",
        "J151301001",
    ]
    assert hydrometry_cfg.sources[0].max_stations == 7


def _check_bretagne_hydrometry_small_bdtopage(
    site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any
) -> None:
    assert site_cfg.input.mode == "hydrometry"
    assert site_cfg.input.catchments_csv is None
    assert site_cfg.outlets.snap_strategy == "bdtopage_then_dem"
    assert hydrometry_cfg.sources[0].source == "hubeau"
    assert hydrometry_cfg.sources[0].extent == "study_area"
    assert hydrometry_cfg.sources[0].station_ids == [
        "J061161001",
        "J062661001",
        "J110301001",
        "J111401001",
        "J131301001",
        "J132401001",
        "J151301001",
    ]
    assert hydrometry_cfg.sources[0].max_stations == 7


def _check_normandie_dem_area_light(site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any) -> None:
    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.regions == ["Normandie"]
    assert site_cfg.hydrology.network_threshold_area_km2 == pytest.approx(1.0)
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.min_area_km2 == pytest.approx(75.0)
    assert site_cfg.dem_area_light.max_area_km2 == pytest.approx(125.0)
    assert site_cfg.dem_area_light.n_basins == 50
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].regions == ["Normandie"]


def _check_calvados_dem_area_light_fast(site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any) -> None:
    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["014"]
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.n_basins == 10
    assert site_cfg.dem_area_light.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["014"]


def _check_manche_dem_area_light_fast(site_cfg: Any, dem_cfg: Any, hydrometry_cfg: Any) -> None:
    assert site_cfg.input.mode == "dem_area_light"
    assert site_cfg.territory.mode == "admin_departments"
    assert site_cfg.territory.departments == ["050"]
    assert site_cfg.dem_area_light is not None
    assert site_cfg.dem_area_light.target_area_km2 == pytest.approx(100.0)
    assert site_cfg.dem_area_light.n_basins == 10
    assert site_cfg.dem_area_light.max_candidates_before_delineation == 30
    assert dem_cfg is not None
    assert dem_cfg.sources[0].source == "ign_geoplateforme_dem"
    assert dem_cfg.sources[0].departments == ["050"]


@dataclass(frozen=True)
class ExampleCase:
    """One shipped config plus the loaders and checks it is expected to satisfy."""

    config_name: str
    load_dem: bool
    load_hydrometry: bool
    check: Callable[[Any, Any, Any], None]


EXAMPLE_CASES = [
    ExampleCase("bretagne_hydrometry_primary.toml", True, True, _check_bretagne_hydrometry_primary),
    ExampleCase(
        "bretagne_hydrometry_50_500_hubeau_preview.toml",
        True,
        True,
        _check_bretagne_hydrometry_hubeau_preview,
    ),
    ExampleCase(
        "auvergne_rhone_alpes_hydrometry_50_150.toml",
        True,
        True,
        _check_auvergne_rhone_alpes_hydrometry,
    ),
    ExampleCase(
        "auvergne_rhone_alpes_hydrometry_preview.toml",
        True,
        True,
        _check_auvergne_rhone_alpes_hydrometry_preview,
    ),
    ExampleCase(
        "bretagne_hydrometry_50_500_small.toml", True, True, _check_bretagne_hydrometry_small
    ),
    ExampleCase(
        "bretagne_hydrometry_50_500_small_bdtopage.toml",
        False,
        True,
        _check_bretagne_hydrometry_small_bdtopage,
    ),
    ExampleCase(
        "normandie_dem_area_light_100km2.toml", True, False, _check_normandie_dem_area_light
    ),
    ExampleCase(
        "calvados_dem_area_light_100km2_fast.toml",
        True,
        False,
        _check_calvados_dem_area_light_fast,
    ),
    ExampleCase(
        "manche_dem_area_light_100km2_fast.toml", True, False, _check_manche_dem_area_light_fast
    ),
]


@pytest.mark.fast
@pytest.mark.parametrize(
    "case",
    EXAMPLE_CASES,
    ids=[case.config_name.removesuffix(".toml") for case in EXAMPLE_CASES],
)
def test_example_config_loads(case: ExampleCase) -> None:
    config_path = EXAMPLE_ROOT / "configs" / case.config_name

    site_cfg = load_site_selection_config(config_path)
    dem_cfg = load_data_dem_config_for_site_selection(config_path) if case.load_dem else None
    hydrometry_cfg = (
        load_hydrometry_config_for_site_selection(config_path) if case.load_hydrometry else None
    )

    case.check(site_cfg, dem_cfg, hydrometry_cfg)
