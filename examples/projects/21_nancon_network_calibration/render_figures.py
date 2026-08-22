"""Render the figures of the two-stage calibration of the Nancon.

Four figures read the session straight from the run: the crossing of the two
distances, the trace of the bisection, the cost profile of the storage phase,
and the two-stage card.

Three others need the per-cell supports the criterion builds during a trial and
that nothing persists, so this script rebuilds them from the best run and hands
them over: the confusion map, the overlay of the two networks, and the map of
the downslope distance.

    python examples/projects/21_nancon_network_calibration/render_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import hydromodpy as hmp
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.results.calibration_trials import calibration_trials

PROJECT = Path(__file__).resolve().parent
FIGURES = PROJECT / "figures" / "calibration"

FROM_THE_RUN = (
    "downslope_distance_crossing",
    "bisection_bracket_trace",
    "parameter_cost_profile",
    "abherve_two_stage_card",
)


def _latest_calibration_run(catalog):
    """Return the most recent run that carries calibration trials."""
    runs = catalog.simulations
    for sim_id in runs["sim_id"]:
        run = catalog.run(str(sim_id))
        if run.has_table("calibration_iterations"):
            return run
    return None


def _render(figure_name: str, run, **opts) -> Path | None:
    """Draw one figure, or say why it was skipped."""
    factory = get_figure(figure_name)
    figure = factory() if isinstance(factory, type) else factory
    reason = figure.unavailable_reason(run) if not opts else None
    if reason:
        print(f"  {figure_name}: skipped, {reason}")
        return None

    fig, ax = plt.subplots(figsize=figure.spec.default_figsize)
    try:
        figure.render(run, ax, **opts)
        FIGURES.mkdir(parents=True, exist_ok=True)
        path = FIGURES / f"{figure_name}.png"
        fig.savefig(path, dpi=140, bbox_inches="tight")
        print(f"  {figure_name}: {path.relative_to(PROJECT)}")
        return path
    except Exception as exc:  # noqa: BLE001 - one bad figure must not stop the others
        print(f"  {figure_name}: failed, {type(exc).__name__}: {exc}")
        return None
    finally:
        plt.close(fig)


def main() -> int:
    catalog = hmp.catalog(PROJECT)
    run = _latest_calibration_run(catalog)
    if run is None:
        print("No run in this project carries calibration trials. Run the calibration first:")
        print(
            "  hmp calibrate examples/projects/21_nancon_network_calibration/"
            "calibration_two_stage.toml"
        )
        return 1

    trials = calibration_trials(run)
    print(f"Session of run {run.name}: {len(trials)} trials")

    print("Figures read from the run:")
    for name in FROM_THE_RUN:
        _render(name, run)

    print()
    print("Figures needing the per-cell supports of the criterion:")
    print("  the criterion builds them during a trial and no run persists them,")
    print("  so they are drawn by passing the masks to render(). See the README.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
