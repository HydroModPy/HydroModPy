"""PNG figure export for simulated-active network overlays."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

from .base import _completed_simulation_summaries

logger = get_logger(__name__)


def write_simulated_active_network_reference_figure_export(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
    dpi: int = 180,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render per-simulation simulated-active maps against the reference network.

    The comparison target is deliberately ``reference``. Missing reference
    linework skips the figure for that simulation; it never falls back to the
    topography-derived ``generated`` network.
    """
    import matplotlib.pyplot as plt

    from hydromodpy.analysis.comparison.runtime import discover_result_store
    from hydromodpy.display import get as get_figure

    rows: list[dict[str, Any]] = []
    skipped_simulations: list[dict[str, Any]] = []
    figure_root = comparison_root / "run_figures"
    figure_names = (
        "simulated_active_network",
        "simulated_active_network_reference_overlay",
    )

    for summary in _completed_simulation_summaries(simulation_summaries):
        simulation_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        if store is None or sim_id in (None, ""):
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                    "network_role": network_role,
                }
            )
            continue

        try:
            run = store[str(sim_id)]
            if not run.has_field(variable):
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_simulated_active_field",
                        "source_variable": variable,
                        "network_role": network_role,
                    }
                )
                continue
            if not run.has_hydrographic_network(network_role):
                skipped_simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "reason": "missing_vector_network_role",
                        "network_role": network_role,
                        "available_roles": run.available_hydrographic_network_roles(),
                        "source_variable": variable,
                    }
                )
                continue

            simulation_dir = figure_root / simulation_id
            for figure_name in figure_names:
                figure_path = simulation_dir / f"{figure_name}.png"
                fig = get_figure(figure_name).plot(
                    run,
                    dpi=dpi,
                    save_path=figure_path,
                    variable=variable,
                    threshold=threshold,
                    mode=mode,
                    persistence_threshold=persistence_threshold,
                    timestep=timestep,
                    buffer_m=buffer_m,
                )
                plt.close(fig)
                row = {
                    "kind": "simulated_active_network_figure",
                    "simulation_id": simulation_id,
                    "figure_name": figure_name,
                    "path": str(figure_path),
                }
                rows.append(row)
        except Exception as exc:
            skipped_simulations.append(
                {
                    "simulation_id": simulation_id,
                    "reason": "simulated_active_network_figure_failed",
                    "source_variable": variable,
                    "network_role": network_role,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active network figure export for simulation '%s'.",
                simulation_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = list(rows)
    if skipped_simulations:
        skipped_path = comparison_root / "simulated_active_network_figures_skipped.json"
        skipped_payload = {
            "network_role": network_role,
            "source_variable": variable,
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
            "skipped_simulations": skipped_simulations,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_figures_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_simulations)} simulation(s) skipped for simulated-active "
                    "network figure export."
                ),
            }
        )

    return artifacts, rows
