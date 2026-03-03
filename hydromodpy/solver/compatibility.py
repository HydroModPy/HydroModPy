"""Hard-coded compatibility rules between process types and solvers."""

from __future__ import annotations

ProcessSolverKey = tuple[str, str]

PROCESS_SOLVER_REQUIREMENTS: dict[ProcessSolverKey, tuple[ProcessSolverKey, ...]] = {
    ("flow", "modflownwt"): (),
    ("flow", "modflow6"): (),
    ("particles", "modpath"): (("flow", "modflownwt"),),
    ("transport", "mt3dms"): (("flow", "modflownwt"),),
    ("transport", "modflow6gwt"): (("flow", "modflow6"),),
}


def is_supported(process_type: str, solver_name: str) -> bool:
    """Return True when the process/solver pair is supported."""
    return (process_type, solver_name) in PROCESS_SOLVER_REQUIREMENTS


def required_bindings(process_type: str, solver_name: str) -> tuple[ProcessSolverKey, ...]:
    """Return the required earlier process/solver pairs for a given pair."""
    key = (process_type, solver_name)
    if key not in PROCESS_SOLVER_REQUIREMENTS:
        raise ValueError(
            f"Unsupported simulation process/solver pair: {process_type}/{solver_name}."
        )
    return PROCESS_SOLVER_REQUIREMENTS[key]
