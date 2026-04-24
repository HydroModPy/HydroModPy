"""Results-config step - align derived flags with the planned run set."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.config import ResultsConfig
    from hydromodpy.simulation.planning.plan import SimulationPlan


def step_configure_results(
    user_cfg: ResultsConfig,
    plan: SimulationPlan,
) -> ResultsConfig:
    """Return a ResultsConfig whose seepage flags track the plan content.

    concentration_seepage and mass_seepage only make sense when a transport
    process is present. Everything else in the TOML is preserved verbatim.
    """
    has_transport = any(r.process_type == "transport" for r in plan.runs)
    return user_cfg.model_copy(
        update={
            "derived": user_cfg.derived.model_copy(
                update={
                    "concentration_seepage": has_transport,
                    "mass_seepage": has_transport,
                }
            ),
        }
    )
