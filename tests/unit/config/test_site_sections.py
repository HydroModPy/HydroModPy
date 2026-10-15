"""The root sections [site], [sites], [metrics] and [publication]."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.hydromodpy_config import require_site_for_real_catchment
from hydromodpy.core.config_kit.introspect import site_scoped_paths
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError

SYNTHETIC: dict[str, Any] = {"geographic": {"source_mode": "synthetic"}}
REAL: dict[str, Any] = {
    "geographic": {"catchment": {"catch_def": "dem", "dem_init_path": "dem.tif"}}
}


def test_the_four_sections_are_root_sections() -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            **SYNTHETIC,
            "metrics": {"window": {"start": "2001-01-01", "end": "2002-12-31"}},
            "publication": {"license": "etalab-2.0", "creators": ["A. Author"]},
        }
    )
    assert cfg.metrics is not None and cfg.metrics.window is not None
    assert str(cfg.metrics.window.start) == "2001-01-01"
    assert cfg.publication is not None and cfg.publication.license == "etalab-2.0"
    assert cfg.site is None and cfg.sites is None
    for name in ("site", "sites", "metrics", "publication"):
        assert name in HydroModPyConfig.model_fields


def test_a_reversed_metrics_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="before it starts"):
        HydroModPyConfig.model_validate(
            {**SYNTHETIC, "metrics": {"window": {"start": "2002-01-01", "end": "2001-01-01"}}}
        )


def test_site_and_sites_are_refused_together() -> None:
    with pytest.raises(ValidationError, match=r"\[site\] and \[sites\]"):
        HydroModPyConfig.model_validate(
            {**SYNTHETIC, "site": {"name": "nancon"}, "sites": {"table": "sites.csv"}}
        )


def test_a_real_catchment_without_a_site_is_refused_by_the_rule() -> None:
    cfg = HydroModPyConfig.model_construct(
        site=None,
        sites=None,
        geographic=HydroModPyConfig.model_fields["geographic"].annotation.model_validate(
            REAL["geographic"]
        ),
    )
    with pytest.raises(ConfigError) as caught:
        require_site_for_real_catchment(cfg)
    message = str(caught.value)
    assert "catch_def = 'dem'" in message
    assert '[site] with name = "<catchment>"' in message


def test_a_synthetic_domain_needs_no_site() -> None:
    cfg = HydroModPyConfig.model_validate(SYNTHETIC)
    require_site_for_real_catchment(cfg)
    assert cfg.site is None


def test_a_named_site_satisfies_the_rule() -> None:
    cfg = HydroModPyConfig.model_validate({**REAL, "site": {"name": "nancon"}})
    require_site_for_real_catchment(cfg)
    assert cfg.site is not None and cfg.site.name == "nancon"


def test_a_sites_project_takes_its_site_from_the_table() -> None:
    cfg = HydroModPyConfig.model_validate({**REAL, "sites": {"table": "sites.csv"}})
    require_site_for_real_catchment(cfg)


def test_a_toml_real_catchment_without_a_site_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[geographic.catchment]\ncatch_def = "dem"\ndem_init_path = "dem.tif"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match=r"no \[site\] names it"):
        HydroModPyConfig.from_toml(path)


def test_the_workflow_section_is_optional() -> None:
    cfg = HydroModPyConfig.model_validate(SYNTHETIC)
    assert cfg.workflow.mode is None


def test_the_site_scoped_fields_are_listed() -> None:
    paths = set(site_scoped_paths(HydroModPyConfig))
    expected = {
        "geographic.catchment.x_outlet",
        "geographic.catchment.y_outlet",
        "geographic.catchment.polyg_shp_path",
        "data.hydrometry.sources[].station_ids",
        "data.hydrometry.sources[].path",
        "data.hydrometry.sources[].mask_path",
        "data.recharge.sources[].path",
        "data.runoff.sources[].station_ids",
        "data.dem.sources[].mask_path",
        "calibration.observed_station_id",
        "calibration.phases[].observed_station_id",
        "calibration.outputs.*.observes",
        "calibration.outputs.*.stream_geometry_path",
    }
    assert expected <= paths
    # A regional input is shared by every site: not site scoped.
    assert "geographic.catchment.dem_init_path" not in paths
    assert "data.dem.sources[].path" not in paths
    assert "data.geology.sources[].path" not in paths
