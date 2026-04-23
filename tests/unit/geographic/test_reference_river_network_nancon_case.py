"""Non-regression smoke test for the Nançon river-network reference case."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from hydromodpy.spatial.geographic.cases.reference_river_network_nancon.run_case_river_network_nancon import (
    run_reference_river_network_nancon_from_toml,
)
from tests._helpers.whitebox import configure_whitebox_single_thread

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_tmp_config(work_root: Path) -> Path:
    config_path = work_root / "case_config_river_network_nancon.toml"
    dem_path = (REPO_ROOT / "examples" / "data" / "dem" / "DEM_armorican_massif.tif").as_posix()
    out_path = (work_root / "results").as_posix()
    ws_root = work_root.as_posix()

    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{out_path}"',
                f'root = "{ws_root}"',
                "",
                "[geographic]",
                'catch_def = "from_outlet_coord"',
                f'dem_init_path = "{dem_path}"',
                "x_outlet = 389285.910",
                "y_outlet = 6816518.749",
                "snap_dist = 50",
                "buff_area = 20.0",
                'crs_project = "EPSG:2154"',
                'dem_correc_type = "breach"',
                "",
                "[geographic.river_network]",
                "enabled = true",
                'threshold_mode = "area_km2"',
                "threshold_area_km2 = 0.5",
                "prune_short_streams = false",
                "min_stream_length_m = 0.0",
                "compute_strahler_order = true",
                "compute_stream_links = true",
                "all_vertices = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.slow
def test_run_reference_river_network_nancon_case(
    monkeypatch: pytest.MonkeyPatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    """Build one river-network case and check core outputs exist."""
    configure_whitebox_single_thread(monkeypatch)
    work_root = (
        hydromodpy_test_scratch_root
        / "tmp"
        / "unit"
        / f"reference_river_network_nancon_case_{uuid4().hex}"
    )
    work_root.mkdir(parents=True, exist_ok=True)
    config_path = _write_tmp_config(work_root)

    payload = run_reference_river_network_nancon_from_toml(
        config_path,
        output_dir=work_root / "figures",
        show_plot=False,
        write_plot=False,
    )

    river_network_shp = Path(str(payload["river_network_shp"]))
    summary_path = Path(str(payload["river_network_summary_json"]))

    assert payload["figure"] is None
    assert river_network_shp.exists()
    assert summary_path.exists()
    assert int(payload["segment_count"]) > 0
    assert float(payload["network_total_length_m"]) > 0.0

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert bool(summary["enabled"]) is True
    assert str(summary["threshold_mode"]) == "area_km2"
    assert int(summary["segment_count"]) == int(payload["segment_count"])
