"""Pipeline state - the object that flows between pipeline steps.

``PipelineState`` is a frozen, generic dataclass that each step receives as
input and returns a new version of as output. Steps must never mutate a state
instance; instead they produce a successor via :meth:`PipelineState.advance`.

The state is parameterised by the *payload* type ``T``. Concrete payloads are
the typed dataclasses defined below (``ValidatedState``, ``ResolvedState``,
``LoadedState`` …), one per pipeline step transition. The generic parameter
defaults to ``Mapping[str, Any]`` so legacy callers can keep using
``state.data["key"]`` style access.

Typed state hierarchy
---------------------

Each step refines the payload by adding fields. The payloads form an
inheritance chain so a step that consumes ``ResolvedState`` will also accept a
``LoadedState`` (which IS-A ``ResolvedState``):

::

    ValidatedState
    └── ResolvedState
        └── LoadedState
            └── MeshedState
                └── SetupState
                    └── OpenStoreState
                        └── SolverRanState
                            └── ExtractedState
                                └── DerivedState
                                    └── ExportedState
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.state.data import LoadedDataContext
    from hydromodpy.core.state.setup import SetupContext
    from hydromodpy.data.plan import DataLoadPlan
    from hydromodpy.results.zarr_store import SimulationZarr
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.solver.base.protocol import RunResult


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PipelineState(Generic[T]):
    """State traversing the pipeline, immutable between steps."""

    run_id: str
    step_index: int = -1
    step_name: str = ""
    elapsed_ms: float = 0.0
    data: T = field(default_factory=dict)  # type: ignore[assignment]

    def advance(
        self,
        *,
        step_index: int,
        step_name: str,
        elapsed_ms: float = 0.0,
        data: T | None = None,
        **extra: Any,
    ) -> PipelineState[T]:
        """Return a successor state for the next step.

        For the legacy ``Mapping[str, Any]`` payload, ``extra`` keyword
        arguments are merged into a copy of the current ``data`` mapping
        (existing keys are overwritten). For typed payloads, callers should
        pass ``data=`` explicitly with the next-step payload.
        """
        new_data: T
        if data is not None:
            new_data = data
            if extra and isinstance(new_data, Mapping):
                merged = dict(new_data)
                merged.update(extra)
                new_data = merged  # type: ignore[assignment]
        else:
            current = self.data
            if isinstance(current, Mapping):
                merged = dict(current)
                if extra:
                    merged.update(extra)
                new_data = merged  # type: ignore[assignment]
            elif extra:
                raise TypeError(
                    "PipelineState.advance(**extra) only supported for Mapping "
                    "payloads; use data=<new_payload> for typed states."
                )
            else:
                new_data = current
        return replace(
            self,
            step_index=step_index,
            step_name=step_name,
            elapsed_ms=elapsed_ms,
            data=new_data,
        )

    def get(self, key: str, default: Any = None) -> Any:
        if isinstance(self.data, Mapping):
            return self.data.get(key, default)
        return getattr(self.data, key, default)

    def with_data(self, **updates: Any) -> PipelineState[T]:
        """Return a copy of the state with ``data`` merged with ``updates``."""
        if not isinstance(self.data, Mapping):
            raise TypeError(
                "PipelineState.with_data only supported for Mapping payloads; "
                "use replace() with a typed payload otherwise."
            )
        merged = dict(self.data)
        merged.update(updates)
        return replace(self, data=merged)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Typed payloads - one per step transition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidatedState:
    """Payload after step 00 (validate)."""

    config: HydroModPyConfig
    workspace: Path | None = None
    config_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ResolvedState(ValidatedState):
    """Payload after step 01 (resolve)."""

    data_plan: DataLoadPlan | None = None
    sim_plan: SimulationPlan | None = None
    raw_toml: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LoadedState(ResolvedState):
    """Payload after step 02 (load_data)."""

    loaded_context: LoadedDataContext | None = None


@dataclass(frozen=True, slots=True)
class MeshedState(LoadedState):
    """Payload after step 03 / 04 (build_geographic + build_mesh)."""

    mesh_context: Any = None


@dataclass(frozen=True, slots=True)
class SetupState(MeshedState):
    """Payload after step 05 (setup_process)."""

    setup_context: SetupContext | None = None


@dataclass(frozen=True, slots=True)
class OpenStoreState(SetupState):
    """Payload after step 06 (prepare_solver)."""

    sim_zarr: SimulationZarr | None = None


@dataclass(frozen=True, slots=True)
class SolverRanState(OpenStoreState):
    """Payload after step 07 (run_solver)."""

    solver_result: RunResult | None = None
    wall_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ExtractedState(SolverRanState):
    """Payload after step 08 (extract)."""

    extraction_summary: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DerivedState(ExtractedState):
    """Payload after step 09 (derive)."""

    derived_names: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExportedState(DerivedState):
    """Payload after step 10 (export)."""

    export_paths: list[Path] = field(default_factory=list)


__all__ = (
    "PipelineState",
    "ValidatedState",
    "ResolvedState",
    "LoadedState",
    "MeshedState",
    "SetupState",
    "OpenStoreState",
    "SolverRanState",
    "ExtractedState",
    "DerivedState",
    "ExportedState",
)
