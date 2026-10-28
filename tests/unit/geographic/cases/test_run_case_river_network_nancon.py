"""The Nançon river-network reference case builds its network on the Armorican DEM."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from hydromodpy.spatial.geographic.cases.reference_river_network_nancon.run_case_river_network_nancon import (
    run_reference_river_network_nancon_from_toml,
)
from tests._helpers.geographic_cases import CASE_RIVER_NETWORK, NANCON, outlet_case_toml
from tests._helpers.whitebox import configure_whitebox_single_thread


@pytest.mark.slow
@pytest.mark.allow_subprocess  # depression removal runs in a child
def test_run_reference_river_network_nancon_case(
    monkeypatch: pytest.MonkeyPatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    configure_whitebox_single_thread(monkeypatch)
    root = hydromodpy_test_scratch_root / "tmp" / "unit" / f"nancon_{uuid4().hex}"
    config_path = outlet_case_toml(
        root / "case_config_river_network_nancon.toml",
        NANCON,
        root=root,
        river_network=CASE_RIVER_NETWORK,
    )

    payload = run_reference_river_network_nancon_from_toml(
        config_path, output_dir=root / "figures", show_plot=False, write_plot=False
    )

    network = Path(str(payload["hydrographic_network_generated_shp"]))
    summary_path = Path(str(payload["hydrographic_network_generated_summary_json"]))
    assert payload["figure"] is None
    assert network.exists()
    assert summary_path.exists()
    assert "river_network_shp" not in payload
    assert "river_network_summary_json" not in payload
    assert int(payload["segment_count"]) > 0
    assert float(payload["network_total_length_m"]) > 0.0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert bool(summary["enabled"]) is True
    assert str(summary["threshold_mode"]) == "area_km2"
    assert int(summary["segment_count"]) == int(payload["segment_count"])
