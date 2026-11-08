"""Generic helpers shared by transport-family solver adapters.

These functions only read plan types (``RunContext``, ``SimulationPlan``,
``ProcessRun``, ``SolverRun``) and therefore stay in ``solver/base/`` rather
than leaking into a specific solver backend.
"""

from __future__ import annotations

from hydromodpy.core.contracts.solver_model import SolverModel
from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.registry import solvers


def required_flow_model(ctx: RunContext) -> SolverModel:
    """Return the solver model of the single flow run a transport run follows.

    It is the solver model of ``ctx.upstream[0]``, which the runner resolved
    from ``depends_on``.
    """

    if len(ctx.upstream) != 1:
        raise SolverInputError(
            f"Process run '{ctx.run.id}' expected exactly one flow dependency, "
            f"got {len(ctx.upstream)}.",
            run_id=ctx.run.id,
        )
    return ctx.upstream[0].solver_model


def _produces_concentration(run: ProcessRun) -> bool:
    """Whether the adapter for ``run`` writes a concentration field.

    Reads the ``produces_concentration`` attribute declared on the adapter
    class. Unknown adapters default to ``False``.
    """
    if run.process_type != "transport":
        return False
    try:
        cls = solvers.get(run.process_type, run.solver)
    except SolverInputError:
        return False
    return bool(getattr(cls, "produces_concentration", False))


def _concentration_transport_runs(plan: SimulationPlan) -> list[ProcessRun]:
    """Return transport runs that write concentration outputs."""

    return [run for run in plan.runs if _produces_concentration(run)]


def transport_output_suffix(plan: SimulationPlan, run: ProcessRun) -> str:
    """Return the stable suffix used by concentration transport runs."""

    if not _produces_concentration(run):
        raise ValueError(
            f"Transport run '{run.id}' is not a supported concentration transport run."
        )

    for index, planned in enumerate(_concentration_transport_runs(plan), start=1):
        if planned.id == run.id:
            return f"_mt_s{index}"
    raise ValueError(
        f"Transport run '{run.id}' is not part of the concentration transport sequence."
    )
