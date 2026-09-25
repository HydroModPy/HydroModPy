"""Cross-section coherence checks on :class:`HydroModPyConfig`.

The architecture spec (``02_config_pydantic.md`` §3.2) calls for a
cross-section validator firing after individual sub-configs validate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _minimal_geographic() -> GeographicConfig:
    """Build a minimal synthetic geographic section for test scaffolding."""
    return GeographicConfig(source_mode="synthetic")


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": _minimal_geographic(),
    }


def test_data_inference_strict_without_types_is_rejected(tmp_path) -> None:
    bad_data = DataManagersConfig(types=[], inference_mode="strict")
    with pytest.raises(ValidationError) as excinfo:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            data=bad_data,
        )
    assert "inference_mode='strict'" in str(excinfo.value)


def test_data_inference_strict_with_types_is_accepted(tmp_path) -> None:
    ok_data = DataManagersConfig(types=["geology"], inference_mode="strict")
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        data=ok_data,
    )
    assert cfg.data.inference_mode == "strict"


def test_data_inference_warn_without_types_is_accepted(tmp_path) -> None:
    empty_data = DataManagersConfig(types=[], inference_mode="warn")
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        data=empty_data,
    )
    assert cfg.data.inference_mode == "warn"


def test_a_raster_depth_model_without_a_substratum_is_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError, match=r"\[data.substratum\]"):
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            domain={"depth_model": {"kind": "raster"}},
        )


def test_a_raster_depth_model_with_a_substratum_is_accepted(tmp_path) -> None:
    from hydromodpy.data.variables.substratum.config import SubstratumConfig

    raster = tmp_path / "substratum.tif"
    raster.write_bytes(b"")
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        domain={"depth_model": {"kind": "raster", "quantity": "thickness"}},
        data=DataManagersConfig(substratum=SubstratumConfig.from_raster(raster)),
    )

    assert cfg.domain.depth_model.quantity == "thickness"


def test_a_geographic_bottom_path_is_accepted_ignored_and_warned_about() -> None:
    with pytest.warns(DeprecationWarning, match="bottom_path"):
        cfg = GeographicConfig.model_validate(
            {"source_mode": "synthetic", "bottom_path": "bottom.tif"}
        )

    assert "bottom_path" not in cfg.model_dump()
