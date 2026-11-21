"""Which data families each section of a project reads, so the data plan loads them.

A section that computes from loaded data names the families it needs here, and
the data planner activates them without the user listing them in ``[data]``.
The planner reads plain names, so it never imports the sections themselves.
"""

from __future__ import annotations

from hydromodpy.model.forcing.recharge_estimators import ESTIMATORS
from hydromodpy.model.forcing.soil_config import soil_reservoir_of


def families_read_by(cfg: object) -> dict[str, tuple[str, ...]]:
    """The data families each declared section of ``cfg`` reads, keyed by its TOML name."""
    reads: dict[str, tuple[str, ...]] = {}
    soil = soil_reservoir_of(getattr(cfg, "flow", None))
    if soil is not None:
        families = ("precipitation", "etp")
        if soil.snow is not None:
            families += ("temperature",)
        reads["[flow.sinks_sources.recharge.soil]"] = families
    etp = getattr(getattr(cfg, "data", None), "etp", None)
    if etp is not None and etp.formula is not None:
        reads["[data.etp] formula"] = ("temperature",)
    recharge = getattr(getattr(cfg, "data", None), "recharge", None)
    if recharge is not None and recharge.formula is not None:
        reads["[data.recharge] formula"] = ("recharge", *ESTIMATORS[recharge.formula].reads)
    estimates = getattr(cfg, "recharge_estimates", None)
    if estimates is not None:
        reads["[recharge_estimates]"] = estimates.families()
    return reads
