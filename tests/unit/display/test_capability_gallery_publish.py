from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.analysis.capability_gallery import (
    CapabilityGalleryConfig,
    publish_run_to_capability_gallery,
)


def test_publish_run_to_capability_gallery_copies_selected_figures(tmp_path: Path) -> None:
    run_folder = tmp_path / "results_simulations" / "demo"
    figure_dir = run_folder / "_postprocess" / "_figures"
    figure_dir.mkdir(parents=True)
    (figure_dir / "flow_state_triptych.png").write_bytes(b"triptych")
    (figure_dir / "recharge_discharge_cumulative.png").write_bytes(b"cumulative")

    gallery_dir = tmp_path / "examples" / "capability_gallery" / "demo"
    manifest = publish_run_to_capability_gallery(
        run_id="demo",
        run_folder=run_folder,
        config=CapabilityGalleryConfig(
            enabled=True,
            output_dir=gallery_dir,
            case_slug="demo_case",
            assets=(
                "flow_state_triptych.png",
                "recharge_discharge_cumulative.png",
                "missing.png",
            ),
        ),
        solvers=("modflow6", "modflow6gwt"),
    )

    assert manifest is not None
    assert (gallery_dir / "flow_state_triptych.png").read_bytes() == b"triptych"
    assert (gallery_dir / "recharge_discharge_cumulative.png").read_bytes() == b"cumulative"
    manifest_payload = json.loads((gallery_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["case_slug"] == "demo_case"
    assert manifest_payload["run_id"] == "demo"
    assert manifest_payload["solvers"] == ["modflow6", "modflow6gwt"]
    assert manifest_payload["missing_assets"] == ["missing.png"]
    assert [asset["filename"] for asset in manifest_payload["assets"]] == [
        "flow_state_triptych.png",
        "recharge_discharge_cumulative.png",
    ]
