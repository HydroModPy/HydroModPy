from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.display.catchment_report.context import (
    build_context,
    context_artifact_manifest_path,
)
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs


def test_build_context_writes_report_artifact_manifest(tmp_path: Path) -> None:
    run_config = tmp_path / "run_test.toml"
    run_config.write_text("[simulation]\n", encoding="utf-8")
    export_path = tmp_path / "exports" / "test_run" / "timeseries.csv"
    export_path.parent.mkdir(parents=True)
    export_path.write_text(
        "datetime,value\n2020-01-01,1.0\n2020-01-02,2.0\n",
        encoding="utf-8",
    )
    observed_path = tmp_path / "observed.csv"
    observed_path.write_text(
        "datetime,value\n2020-01-01,1.5\n2020-01-02,2.5\n",
        encoding="utf-8",
    )
    inputs = CatchmentReportInputs.from_project_layout(
        output_dir=tmp_path / "report",
        site_label="Test",
        station_label="Station",
        watershed_project_dir=tmp_path,
        context_outputs_dir=tmp_path / "context_outputs",
        simulation_workspace_dir=tmp_path,
        simulation_name="test_run",
        transient_config_name="run_test.toml",
        observed_discharge_path=observed_path,
    )

    build_context(inputs)

    manifest_path = context_artifact_manifest_path(inputs)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {artifact["artifact_id"]: artifact for artifact in payload["artifacts"]}

    assert payload["metadata"]["artifact_scope"] == "catchment.context"
    assert by_id["context.summary"]["status"] == "present"
    assert by_id["observation.discharge.full_timeseries"]["status"] == "present"
    assert by_id["forcing.simulation_window"]["status"] == "present"
    assert by_id["simulation.discharge.observed_comparison"]["status"] == "present"
