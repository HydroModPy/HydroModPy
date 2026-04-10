from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.analysis.display.options import DisplayOptions, DisplaySectionOptions
from hydromodpy.analysis.display.posthoc import GeographicArtifacts, RunArtifacts
from hydromodpy.analysis.display.posthoc_orchestration import plot_posthoc_flow_suite


def test_plot_posthoc_flow_suite_reuses_native_mesh_figures_for_unstructured_outputs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "results_simulations" / "run_a"
    postprocess_dir = run_dir / "_postprocess"
    native_dir = postprocess_dir / "_figures" / "native_mesh"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "flow_watertable_depth_t(0)_time(1).png").write_text("depth", encoding="utf-8")
    (native_dir / "flow_support_overview.png").write_text("overview", encoding="utf-8")

    np.save(
        postprocess_dir / "watertable_elevation",
        {0: np.asarray([9.0, 8.5], dtype=float)},
    )

    run = RunArtifacts.discover(run_dir)
    geo = GeographicArtifacts(geographic_dir=tmp_path / "results_stable" / "geographic")
    options = DisplayOptions(
        enabled=True,
        show=False,
        save=True,
        flow=DisplaySectionOptions(enabled=True),
    )

    plot_posthoc_flow_suite(run, geo, options)

    figure_dir = postprocess_dir / "_figures"
    assert (figure_dir / "watertable_depth.png").exists()
    assert (figure_dir / "flow_support_overview.png").exists()
