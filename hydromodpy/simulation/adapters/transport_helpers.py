"""Generic helpers shared by transport-family solver adapters.

These functions only read simulation-layer types (``RunContext``,
``SimulationPlan``, ``ProcessRun``) and therefore stay in ``simulation/``
rather than leaking into a specific solver backend.
"""

from __future__ import annotations

from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan


def required_flow_model(ctx: RunContext):
    """Return the single flow dependency required by current transport adapters."""

    if len(ctx.dependency_models) != 1:
        raise ValueError(
            f"Process run '{ctx.run.id}' expected exactly one flow dependency, "
            f"got {len(ctx.dependency_models)}."
        )
    return ctx.dependency_models[0]


def _concentration_transport_runs(plan: SimulationPlan) -> list[ProcessRun]:
    """Return transport runs that write concentration outputs."""

    return [
        run
        for run in plan.runs
        if run.process_type == "transport" and run.solver in {"mt3dms", "modflow6gwt"}
    ]


def transport_output_suffix(plan: SimulationPlan, run: ProcessRun) -> str:
    """Return the stable suffix used by concentration transport runs."""

    if run.process_type != "transport" or run.solver not in {"mt3dms", "modflow6gwt"}:
        raise ValueError(
            f"Transport run '{run.id}' is not a supported concentration transport run."
        )

    for index, planned in enumerate(_concentration_transport_runs(plan), start=1):
        if planned.id == run.id:
            return f"_mt_s{index}"
    raise ValueError(
        f"Transport run '{run.id}' is not part of the concentration transport sequence."
    )
