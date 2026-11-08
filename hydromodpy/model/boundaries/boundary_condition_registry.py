"""
Flow boundary-condition registry and runtime bundle helpers.

The normalized `[flow.bc]` payload stores user-facing boundary definitions.
This module keeps the process-level inventory explicit: which identifiers are
canonical and which family they belong to. ``[flow.bc]`` accepts the ids that are
not an advanced package, and their kinds come from the same table. A solver
backend says which ids it builds through its ``supports``, so no backend is named
here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

ALLOWED_BC_APPLICATION_DOMAINS = {
    "top",
    "north side",
    "west side",
    "east side",
    "south side",
}
"""Supported target domains for boundary-condition application.

These values are used by validators and normalizers to reject unsupported
domains early. If one payload defines `application_domain`, the value must be
in this set.
"""

DIRICHLET_BC_CANONICAL_DOMAINS: dict[str, str] = {
    "ocean": "top",
    "stream": "top",
    "north_side": "north side",
    "south_side": "south side",
    "east_side": "east side",
    "west_side": "west side",
}
"""Mapping from canonical Dirichlet identifiers to their implied domain.

This table encodes the process convention:
- key is the boundary-condition id expected in `[flow.bc.dirichlet.<id>]`,
- value is the unique `application_domain` allowed for this id.

Example:
- `north_side` must map to `north side` and cannot target any other domain.
"""

FlowBoundaryFamily = Literal["dirichlet", "head_dependent_exchange", "advanced_package"]
FlowBoundarySupportKind = Literal[
    "side", "ocean_stage", "stream", "stream_reach", "top", "advanced_package"
]

SIDE_DIRICHLET_BC_IDS_ORDERED: tuple[str, ...] = (
    "west_side",
    "east_side",
    "north_side",
    "south_side",
)
"""Stable side-boundary order used by config, runtime, and solver adapters."""


@dataclass(frozen=True)
class FlowBoundaryDefinition:
    """One canonical flow boundary-condition definition.

    The definition is intentionally descriptive. It does not assemble solver
    payloads; it tells adapters which process-level id they are handling and which
    physical family it belongs to.
    """

    id: str
    family: FlowBoundaryFamily
    default_type: str
    default_units: str
    application_domain: str
    support_kind: FlowBoundarySupportKind
    supports_forcing: bool = False
    sinks_sources_table: str | None = None
    """The table of ``[flow.sinks_sources]`` that declares an advanced package, else None."""

    @property
    def declared_at(self) -> str:
        """The table of a file that declares this boundary."""
        if self.sinks_sources_table is not None:
            return f"flow.sinks_sources.{self.sinks_sources_table}"
        return f"flow.bc.{self.id}"


FLOW_BOUNDARY_DEFINITIONS: dict[str, FlowBoundaryDefinition] = {
    "west_side": FlowBoundaryDefinition(
        id="west_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["west_side"],
        support_kind="side",
        supports_forcing=True,
    ),
    "east_side": FlowBoundaryDefinition(
        id="east_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["east_side"],
        support_kind="side",
        supports_forcing=True,
    ),
    "north_side": FlowBoundaryDefinition(
        id="north_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["north_side"],
        support_kind="side",
        supports_forcing=True,
    ),
    "south_side": FlowBoundaryDefinition(
        id="south_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["south_side"],
        support_kind="side",
        supports_forcing=True,
    ),
    "stream": FlowBoundaryDefinition(
        id="stream",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["stream"],
        support_kind="stream",
        supports_forcing=True,
    ),
    "ocean": FlowBoundaryDefinition(
        id="ocean",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["ocean"],
        support_kind="ocean_stage",
        supports_forcing=True,
    ),
    "drainage": FlowBoundaryDefinition(
        id="drainage",
        family="head_dependent_exchange",
        default_type="drain",
        default_units="m2/s",
        application_domain="top",
        support_kind="top",
    ),
    "lake": FlowBoundaryDefinition(
        id="lake",
        family="advanced_package",
        default_type="lake",
        default_units="m",
        application_domain="top",
        support_kind="advanced_package",
        supports_forcing=True,
        sinks_sources_table="lakes",
    ),
    # SFR (streamflow routing) is an advanced package. It reads the
    # flow.sinks_sources['sfr'] payload and is lake-independent: a declared network
    # routes streamflow on its own; its optional MVR coupling to a lake is data on
    # the SFR payload, not a separate boundary id.
    "sfr": FlowBoundaryDefinition(
        id="sfr",
        family="advanced_package",
        default_type="sfr",
        default_units="m3/s",
        application_domain="stream_reach",
        support_kind="stream_reach",
        supports_forcing=True,
        sinks_sources_table="sfr",
    ),
}


FORCING_CAPABLE_DIRICHLET_BC_IDS: frozenset[str] = frozenset(
    bc_id
    for bc_id, definition in FLOW_BOUNDARY_DEFINITIONS.items()
    if definition.family == "dirichlet" and definition.supports_forcing
)
"""Dirichlet ids whose head may follow a chronicle rather than stay a number.

A tide and a stream stage move, and every backend that builds these boundaries
already reads their head as one value per stress period.
"""
"""Canonical boundary-condition definitions supported by the flow process."""

SUPPORTED_FLOW_BOUNDARY_IDS = frozenset(FLOW_BOUNDARY_DEFINITIONS)
"""All canonical flow boundary ids, the names ``FlowConfig.active_bc`` can hold."""

FLOW_BC_IDS: tuple[str, ...] = tuple(
    bc_id
    for bc_id, definition in FLOW_BOUNDARY_DEFINITIONS.items()
    if definition.family != "advanced_package"
)
"""The ids a ``[flow.bc.<id>]`` table may name, in the order of the table.

A lake and a stream network are advanced packages, declared under ``[flow.sinks_sources]``.
"""

FlowBcId = Literal[*FLOW_BC_IDS]
"""The type of a key of ``[flow.bc]``."""

FLOW_BC_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(FLOW_BOUNDARY_DEFINITIONS[bc_id].default_type for bc_id in FLOW_BC_IDS)
)
"""The kinds a ``[flow.bc]`` payload can have, read from the ``default_type`` of its ids."""


def boundary_definition(bc_id: str) -> FlowBoundaryDefinition | None:
    """Return the canonical definition for one boundary id, when known."""
    return FLOW_BOUNDARY_DEFINITIONS.get(str(bc_id).strip())


def _normalize_id_sequence(values: Iterable[object] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        bc_id = str(raw_value).strip()
        if bc_id == "" or bc_id in seen:
            continue
        seen.add(bc_id)
        out.append(bc_id)
    return tuple(out)


@dataclass(frozen=True)
class BoundaryConditionBundle:
    """Configured and active flow boundary conditions, read by every backend.

    ``conditions`` maps a boundary id to its typed payload, and ``active_ids``
    lists the ids the run builds. A backend reads ``Model.boundaries``, whose
    ``conditions`` is a read-only mapping, through ``get``, ``is_active`` and
    ``active_side_dirichlet_ids``.
    """

    conditions: Mapping[str, object]
    active_ids: tuple[str, ...]

    @classmethod
    def from_flow(cls, flow: object) -> BoundaryConditionBundle:
        """Build a bundle from one Flow-like runtime object."""
        conditions = getattr(flow, "boundary_conditions", {})
        if not isinstance(conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return cls(
            conditions=conditions,
            active_ids=_normalize_id_sequence(getattr(flow, "active_bc", ())),
        )

    def is_active(self, bc_id: str) -> bool:
        """Return True when one boundary id is active for this run."""
        return str(bc_id).strip() in self.active_ids

    def get(self, bc_id: str, default=None):
        """Return one configured boundary payload."""
        return self.conditions.get(str(bc_id).strip(), default)

    def active_side_dirichlet_ids(self) -> tuple[str, ...]:
        """Return active side Dirichlet ids in canonical solver order."""
        active = set(self.active_ids)
        return tuple(bc_id for bc_id in SIDE_DIRICHLET_BC_IDS_ORDERED if bc_id in active)

    def unknown_active_ids(self) -> tuple[str, ...]:
        """Return active ids that are not canonical flow boundary definitions."""
        return tuple(bc_id for bc_id in self.active_ids if bc_id not in SUPPORTED_FLOW_BOUNDARY_IDS)

    def active_ids_outside(self, supports: frozenset[str]) -> tuple[str, ...]:
        """Return the active canonical ids a backend leaves out of its ``supports``."""
        return tuple(
            bc_id
            for bc_id in self.active_ids
            if bc_id in SUPPORTED_FLOW_BOUNDARY_IDS and bc_id not in supports
        )


def boundary_condition_bundle_from_flow(flow: object) -> BoundaryConditionBundle:
    """Return the current boundary-condition bundle of a setup ``Flow``.

    The bundle the flow keeps is returned while its conditions and active ids
    are still those of the flow, and rebuilt otherwise.
    """
    bundle = getattr(flow, "boundary_condition_bundle", None)
    if isinstance(bundle, BoundaryConditionBundle):
        current_conditions = getattr(flow, "boundary_conditions", {})
        current_active_ids = _normalize_id_sequence(getattr(flow, "active_bc", ()))
        if bundle.conditions is current_conditions and bundle.active_ids == current_active_ids:
            return bundle
    return BoundaryConditionBundle.from_flow(flow)


def boundary_conditions_mapping_from_flow(flow: object) -> Mapping[str, object]:
    """Return the configured boundary conditions of a setup ``Flow``, for the data binders."""
    return boundary_condition_bundle_from_flow(flow).conditions


__all__ = [
    "ALLOWED_BC_APPLICATION_DOMAINS",
    "BoundaryConditionBundle",
    "DIRICHLET_BC_CANONICAL_DOMAINS",
    "FORCING_CAPABLE_DIRICHLET_BC_IDS",
    "FLOW_BC_IDS",
    "FLOW_BC_KINDS",
    "FLOW_BOUNDARY_DEFINITIONS",
    "FlowBcId",
    "FlowBoundaryDefinition",
    "FlowBoundaryFamily",
    "FlowBoundarySupportKind",
    "SIDE_DIRICHLET_BC_IDS_ORDERED",
    "SUPPORTED_FLOW_BOUNDARY_IDS",
    "boundary_condition_bundle_from_flow",
    "boundary_conditions_mapping_from_flow",
    "boundary_definition",
]
