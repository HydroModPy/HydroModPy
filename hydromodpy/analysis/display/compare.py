"""Post-hoc comparison display — ``hmp display compare --sim A --sim B``.

Reads completed simulation results from the project ResultStore and
generates comparative figures/metrics.  This is analysis, not a workflow:
simulations must already have been run independently.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def run_display_compare(
    *,
    sim_names: list[str],
    project_dir: Path | None = None,
) -> dict:
    """Generate comparison figures for two or more completed simulations.

    Parameters
    ----------
    sim_names:
        Names (or sim_ids) of completed simulations in the ResultStore.
    project_dir:
        Project directory containing ``project.duckdb``.  When *None*,
        defaults to the current working directory.

    Returns
    -------
    dict
        Summary with generated figure paths.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    db_path = project_dir / "project.duckdb"
    if not db_path.exists():
        print(
            f"No project store found at {project_dir}.\n"
            "Run simulations first with: hmp run <config.toml>",
            file=sys.stderr,
        )
        sys.exit(1)

    from hydromodpy.results.store import ResultStore

    store = ResultStore(project_dir)
    available = store.list_simulations()
    if available.empty:
        store.close()
        print("No simulations found in the project store.", file=sys.stderr)
        sys.exit(1)

    available_names = set(available["name"].tolist()) | set(
        str(sid) for sid in available["sim_id"].tolist()
    )
    missing = [s for s in sim_names if s not in available_names]
    if missing:
        store.close()
        print(
            f"Simulation(s) not found: {', '.join(missing)}\n"
            f"Available: {', '.join(sorted(available_names))}",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info(
        "[compare] Comparing %d simulations: %s",
        len(sim_names),
        ", ".join(sim_names),
    )

    # Delegate to the analysis/comparison layer.
    from hydromodpy.analysis.comparison.metrics import build_comparison_metrics
    from hydromodpy.analysis.comparison.visuals import generate_comparison_figures

    metrics = build_comparison_metrics(
        store=store,
        sim_names=sim_names,
    )
    figure_paths = generate_comparison_figures(
        store=store,
        sim_names=sim_names,
        output_dir=project_dir / "_comparison",
    )

    store.close()

    summary = {
        "mode": "display_compare",
        "sim_names": sim_names,
        "metrics": metrics,
        "figure_paths": [str(p) for p in figure_paths],
    }

    if figure_paths:
        print(
            f"Generated {len(figure_paths)} comparison figure(s) in "
            f"{project_dir / '_comparison'}",
            file=sys.stderr,
        )
    else:
        print("No comparison figures generated.", file=sys.stderr)

    return summary
