"""
Flow boundary-condition registry and runtime bundle helpers.

The normalized `[flow.bc]` payload stores user-facing boundary definitions.
This module keeps the process-level inventory explicit: which identifiers are
canonical, which family they belong to, and which backend slices currently know
how to translate them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from hydromodpy.physics.flow.boundary_conditions import (
    DIRICHLET_BC_CANONICAL_DOMAINS,
)

FlowBoundaryFamily = Literal["dirichlet", "head_dependent_exchange", "advanced_package"]
FlowBoundarySupportKind = Literal["side", "ocean_stage", "stream", "top", "advanced_package"]
FlowBoundaryBackend = Literal["modflow6", "modflow_nwt", "boussinesq"]

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
    payloads; it tells adapters which process-level id they are handling, which
    physical family it belongs to, and which backend slices claim support.
    """

    id: str
    family: FlowBoundaryFamily
    default_type: str
    default_units: str
    application_domain: str
    support_kind: FlowBoundarySupportKind
    supported_backends: tuple[FlowBoundaryBackend, ...]
    backend_packages: Mapping[FlowBoundaryBackend, str]
    supports_forcing: bool = False

    def supports_backend(self, backend: str) -> bool:
        """Return whether one backend advertises support for this boundary."""
        return str(backend) in self.supported_backends

    def package_for_backend(self, backend: str) -> str | None:
        """Return the backend package/operator name used for this boundary."""
        backend_name = str(backend).strip()
        for known_backend, package in self.backend_packages.items():
            if known_backend == backend_name:
                return package
        return None


FLOW_BOUNDARY_DEFINITIONS: dict[str, FlowBoundaryDefinition] = {
    "west_side": FlowBoundaryDefinition(
        id="west_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["west_side"],
        support_kind="side",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "modflow_nwt": "BAS/CHD",
            "boussinesq": "prescribed_head",
        },
        supports_forcing=True,
    ),
    "east_side": FlowBoundaryDefinition(
        id="east_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["east_side"],
        support_kind="side",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "modflow_nwt": "BAS/CHD",
            "boussinesq": "prescribed_head",
        },
        supports_forcing=True,
    ),
    "north_side": FlowBoundaryDefinition(
        id="north_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["north_side"],
        support_kind="side",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "modflow_nwt": "BAS/CHD",
            "boussinesq": "prescribed_head",
        },
        supports_forcing=True,
    ),
    "south_side": FlowBoundaryDefinition(
        id="south_side",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["south_side"],
        support_kind="side",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "modflow_nwt": "BAS/CHD",
            "boussinesq": "prescribed_head",
        },
        supports_forcing=True,
    ),
    "stream": FlowBoundaryDefinition(
        id="stream",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["stream"],
        support_kind="stream",
        supported_backends=("modflow6", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "boussinesq": "prescribed_head",
        },
    ),
    "ocean": FlowBoundaryDefinition(
        id="ocean",
        family="dirichlet",
        default_type="dirichlet",
        default_units="m",
        application_domain=DIRICHLET_BC_CANONICAL_DOMAINS["ocean"],
        support_kind="ocean_stage",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "CHD",
            "modflow_nwt": "BAS/CHD",
            "boussinesq": "prescribed_head",
        },
    ),
    "drainage": FlowBoundaryDefinition(
        id="drainage",
        family="head_dependent_exchange",
        default_type="cauchy",
        default_units="m2/s",
        application_domain="top",
        support_kind="top",
        supported_backends=("modflow6", "modflow_nwt", "boussinesq"),
        backend_packages={
            "modflow6": "DRN",
            "modflow_nwt": "DRN",
            "boussinesq": "top_drainage",
        },
    ),
    "lake": FlowBoundaryDefinition(
        id="lake",
        family="advanced_package",
        default_type="lake",
        default_units="m",
        application_domain="top",
        support_kind="advanced_package",
        supported_backends=("modflow6",),
        backend_packages={
            "modflow6": "LAK",
        },
        supports_forcing=True,
    ),
    # 'reservoir' is an accepted synonym of 'lake': both map to the MF6 LAK
    # package and read the single flow.sinks_sources['lakes'] payload (there is no
    # separate 'reservoirs' payload). Either id in active_bc activates the lake.
    "reservoir": FlowBoundaryDefinition(
        id="reservoir",
        family="advanced_package",
        default_type="reservoir",
        default_units="m",
        application_domain="top",
        support_kind="advanced_package",
        supported_backends=("modflow6",),
        backend_packages={
            "modflow6": "LAK",
        },
        supports_forcing=True,
    ),
}
"""Canonical boundary-condition definitions supported by the flow process."""

SUPPORTED_FLOW_BOUNDARY_IDS = frozenset(FLOW_BOUNDARY_DEFINITIONS)
"""All canonical flow boundary ids accepted by ``flow.active_bc``."""


def boundary_definition(bc_id: str) -> FlowBoundaryDefinition | None:
    """Return the canonical definition for one boundary id, when known."""
    return FLOW_BOUNDARY_DEFINITIONS.get(str(bc_id).strip())


def side_dirichlet_boundary_ids() -> tuple[str, ...]:
    """Return side Dirichlet ids in a stable solver-facing order."""
    return SIDE_DIRICHLET_BC_IDS_ORDERED


def canonical_dirichlet_boundary_ids() -> tuple[str, ...]:
    """Return all canonical Dirichlet ids in a stable order."""
    return (*SIDE_DIRICHLET_BC_IDS_ORDERED, "stream", "ocean")


def supported_boundary_ids_for_backend(backend: str) -> frozenset[str]:
    """Return canonical active boundary ids supported by one backend slice."""
    backend_name = str(backend).strip()
    return frozenset(
        bc_id
        for bc_id, definition in FLOW_BOUNDARY_DEFINITIONS.items()
        if definition.supports_backend(backend_name)
    )


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
    """Runtime view grouping configured and active flow boundary conditions."""

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

    def get_active(self, bc_id: str, default=None):
        """Return one configured boundary payload only when active."""
        normalized_id = str(bc_id).strip()
        if normalized_id not in self.active_ids:
            return default
        return self.conditions.get(normalized_id, default)

    def require_active(self, bc_id: str) -> object:
        """Return one active boundary or raise a clear contract error."""
        normalized_id = str(bc_id).strip()
        boundary = self.get_active(normalized_id)
        if boundary is None:
            raise ValueError(f"Active boundary '{normalized_id}' is missing from flow.bc.")
        return boundary

    def active_defined_items(self) -> Iterator[tuple[str, object]]:
        """Yield ``(id, boundary)`` pairs for active boundaries that are defined."""
        for bc_id in self.active_ids:
            boundary = self.conditions.get(bc_id)
            if boundary is not None:
                yield bc_id, boundary

    def active_definition_items(
        self,
        *,
        family: FlowBoundaryFamily | None = None,
        backend: FlowBoundaryBackend | str | None = None,
    ) -> Iterator[tuple[str, object, FlowBoundaryDefinition]]:
        """Yield active defined boundaries with their canonical definition."""
        for bc_id, boundary in self.active_defined_items():
            definition = boundary_definition(bc_id)
            if definition is None:
                continue
            if family is not None and definition.family != family:
                continue
            if backend is not None and not definition.supports_backend(str(backend)):
                continue
            yield bc_id, boundary, definition

    def active_side_dirichlet_ids(self) -> tuple[str, ...]:
        """Return active side Dirichlet ids in canonical solver order."""
        active = set(self.active_ids)
        return tuple(bc_id for bc_id in SIDE_DIRICHLET_BC_IDS_ORDERED if bc_id in active)

    def missing_active_ids(self) -> tuple[str, ...]:
        """Return active ids that have no configured boundary payload."""
        return tuple(bc_id for bc_id in self.active_ids if bc_id not in self.conditions)

    def unknown_active_ids(self) -> tuple[str, ...]:
        """Return active ids that are not canonical flow boundary definitions."""
        return tuple(bc_id for bc_id in self.active_ids if bc_id not in SUPPORTED_FLOW_BOUNDARY_IDS)

    def unsupported_active_ids(self, backend: str) -> tuple[str, ...]:
        """Return active canonical ids not supported by one backend slice."""
        supported = supported_boundary_ids_for_backend(backend)
        return tuple(
            bc_id
            for bc_id in self.active_ids
            if bc_id in SUPPORTED_FLOW_BOUNDARY_IDS and bc_id not in supported
        )


def boundary_condition_bundle_from_flow(flow: object) -> BoundaryConditionBundle:
    """Return the current boundary-condition bundle for a Flow-like object."""
    bundle = getattr(flow, "boundary_condition_bundle", None)
    if isinstance(bundle, BoundaryConditionBundle):
        current_conditions = getattr(flow, "boundary_conditions", {})
        current_active_ids = _normalize_id_sequence(getattr(flow, "active_bc", ()))
        if bundle.conditions is current_conditions and bundle.active_ids == current_active_ids:
            return bundle
    return BoundaryConditionBundle.from_flow(flow)


def boundary_conditions_mapping_from_flow(flow: object) -> Mapping[str, object]:
    """Return configured boundary conditions from a Flow-like object."""
    return boundary_condition_bundle_from_flow(flow).conditions


def is_boundary_condition_active(flow: object, bc_id: str) -> bool:
    """Return whether one boundary id is active on a Flow-like object."""
    return boundary_condition_bundle_from_flow(flow).is_active(bc_id)


def active_side_dirichlet_boundary_ids(flow: object) -> tuple[str, ...]:
    """Return active side Dirichlet ids for one Flow-like object."""
    return boundary_condition_bundle_from_flow(flow).active_side_dirichlet_ids()


__all__ = [
    "BoundaryConditionBundle",
    "FLOW_BOUNDARY_DEFINITIONS",
    "FlowBoundaryBackend",
    "FlowBoundaryDefinition",
    "FlowBoundaryFamily",
    "FlowBoundarySupportKind",
    "SIDE_DIRICHLET_BC_IDS_ORDERED",
    "SUPPORTED_FLOW_BOUNDARY_IDS",
    "active_side_dirichlet_boundary_ids",
    "boundary_condition_bundle_from_flow",
    "boundary_conditions_mapping_from_flow",
    "boundary_definition",
    "canonical_dirichlet_boundary_ids",
    "is_boundary_condition_active",
    "side_dirichlet_boundary_ids",
    "supported_boundary_ids_for_backend",
]
