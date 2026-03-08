"""Compatibility matrix used by the simulation planner.

This module answers one narrow question for the orchestration layer:

"Given a planned ``(process_type, solver_name)`` pair, which earlier
process/solver capabilities must already exist?"

The rules are intentionally hard-coded and explicit. They describe
*capability-level* compatibility, not concrete run ids. For example:

- ``("transport", "mt3dms")`` requires an earlier
  ``("flow", "modflownwt")`` capability;
- ``("transport", "modflow6gwt")`` requires an earlier
  ``("flow", "modflow6")`` capability.

The planner uses these static requirements, then resolves them to exact
``ProcessRun`` ids based on the user-declared order.
"""

from __future__ import annotations

ProcessSolverKey = tuple[str, str]

# Each key is one concrete process/solver pair the planner may emit.
# Each value lists the earlier capabilities that must already exist before that
# pair can run. An empty tuple means the pair is a root capability and may
# appear first in the plan.
PROCESS_SOLVER_REQUIREMENTS: dict[ProcessSolverKey, tuple[ProcessSolverKey, ...]] = {
    # Flow solvers are root producers: they do not require an earlier run.
    ("flow", "modflownwt"): (),
    ("flow", "modflow6"): (),
    # Transport solvers depend on a compatible flow backend already planned
    # earlier. The planner later binds these capability requirements to exact
    # upstream run ids such as ``flow_main::modflownwt``.
    ("transport", "modpath"): (("flow", "modflownwt"),),
    ("transport", "mt3dms"): (("flow", "modflownwt"),),
    ("transport", "modflow6gwt"): (("flow", "modflow6"),),
    # Post-processing and display phases — stubs registered for extensibility.
    # No dependency requirements (adapters inspect state at runtime).
    ("postprocess", "timeseries"): (),
    ("postprocess", "netcdf"): (),
    ("display", "flow"): (),
    ("display", "transport"): (),
}


def known_process_types() -> set[str]:
    """Return the set of process types registered in the compatibility matrix."""
    return {key[0] for key in PROCESS_SOLVER_REQUIREMENTS}


def is_supported(process_type: str, solver_name: str) -> bool:
    """Return ``True`` when the process/solver pair is known to the matrix.

    This is a pure membership check. It does not validate ordering and does not
    resolve dependencies; it only answers whether the pair is declared in
    ``PROCESS_SOLVER_REQUIREMENTS``.
    """
    return (process_type, solver_name) in PROCESS_SOLVER_REQUIREMENTS


def register_process_solver(
    process_type: str,
    solver_name: str,
    requires: tuple[ProcessSolverKey, ...] = (),
) -> None:
    """Register a new process/solver pair with its dependency requirements.

    This allows external modules to extend the compatibility matrix without
    modifying this file directly.
    """
    key = (process_type, solver_name)
    if key in PROCESS_SOLVER_REQUIREMENTS:
        raise ValueError(
            f"Process/solver pair already registered: {process_type}/{solver_name}."
        )
    PROCESS_SOLVER_REQUIREMENTS[key] = requires


def required_bindings(process_type: str, solver_name: str) -> tuple[ProcessSolverKey, ...]:
    """Return the earlier capability requirements for one process/solver pair.

    The returned tuple contains *capabilities*, not concrete run ids. Example:

    - ``required_bindings("transport", "mt3dms")`` returns
      ``(("flow", "modflownwt"),)``

    The planner then uses that requirement to find the most recent earlier run
    that provides this capability and records its exact ``ProcessRun.id`` in the
    final plan.
    """
    key = (process_type, solver_name)
    # Fail fast on unsupported pairs so the planner can produce a precise
    # configuration error instead of silently assuming no dependencies.
    if key not in PROCESS_SOLVER_REQUIREMENTS:
        raise ValueError(
            f"Unsupported simulation process/solver pair: {process_type}/{solver_name}."
        )
    return PROCESS_SOLVER_REQUIREMENTS[key]
