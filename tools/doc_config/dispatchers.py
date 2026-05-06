"""Declarative table of TOML sub-section dispatchers.

A *dispatcher* is one TOML path whose payload type is `dict[str, ...]` or
`list[BaseModel]` at the parent level, but whose actual sub-payloads
follow a known schema. Examples:

- ``[flow.bc.dirichlet.<id>]`` resolves to ``FlowBoundaryConditionConfig``,
- ``[flow.param.<id>.field]`` resolves to ``FieldBaseSection``,
- ``[[data.recharge.sources]]`` is a list of ``RechargeSourceConfig``.

The doc generator reads this table and renders a "Dynamic sub-tables"
appendix on the relevant per-section pages so users see the full payload
schema hidden behind the parent dict.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class DispatcherEntry:
    """One dispatched TOML sub-section."""

    section_name: str
    pattern: str
    model: type[BaseModel]
    description: str
    ids: tuple[str, ...] = ()
    note: str = ""


def _flow_dispatchers() -> list[DispatcherEntry]:
    from hydromodpy.physics.flow.boundary_conditions import (
        DIRICHLET_BC_CANONICAL_DOMAINS,
        FlowBoundaryConditionConfig,
        FlowBoundaryForcingConfig,
    )
    from hydromodpy.physics.flow.sinks_sources.wells import FlowWellConfig
    from hydromodpy.spatial.field.core.field_param_config import (
        FieldBaseSection,
        FieldHeterogeneousSection,
        FieldHomogeneousSection,
        FieldVerticalProfileSection,
    )

    dirichlet_ids = tuple(sorted(DIRICHLET_BC_CANONICAL_DOMAINS.keys()))

    return [
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.bc.dirichlet.<id>]",
            model=FlowBoundaryConditionConfig,
            description=(
                "Dirichlet boundary condition payload. ``<id>`` selects the "
                "implied application domain via "
                "``DIRICHLET_BC_CANONICAL_DOMAINS``."
            ),
            ids=dirichlet_ids,
            note=(
                "Side ids (``north_side``, ``south_side``, ``east_side``, "
                "``west_side``) accept an optional ``forcing`` payload "
                "(see below). Default units: ``m``."
            ),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.bc.cauchy.drainage]",
            model=FlowBoundaryConditionConfig,
            description=("Cauchy drainage boundary condition. ``application_domain`` is required."),
            note="Default units: ``m2/s``.",
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.bc.robin.drainage]",
            model=FlowBoundaryConditionConfig,
            description=("Robin drainage boundary condition. ``application_domain`` is required."),
            note="Default units: ``m2/s``.",
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.bc.<id>.forcing]  (mode='constant'|'csv')",
            model=FlowBoundaryForcingConfig,
            description=(
                "Optional time-varying head forcing applied to a side Dirichlet boundary."
            ),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.param.<id>.field]",
            model=FieldBaseSection,
            description=(
                "Field-parameter base block: identifier, kind, units. "
                "``<id>`` matches one entry of ``flow.param_list``."
            ),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.param.<id>.field_homogeneous]",
            model=FieldHomogeneousSection,
            description=("Homogeneous mode payload (constant scalar value across the support)."),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.param.<id>.field_heterogeneous]",
            model=FieldHeterogeneousSection,
            description=("Heterogeneous mode payload (per-zone or raster value source)."),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.param.<id>.field_vertical_profile]",
            model=FieldVerticalProfileSection,
            description=("Optional depth-profile law applied on top of the planar field."),
        ),
        DispatcherEntry(
            section_name="flow",
            pattern="[flow.sinks_sources.wells.<id>]",
            model=FlowWellConfig,
            description=("Pumping or injection well payload. ``<id>`` is a free-form identifier."),
        ),
    ]


def _data_dispatchers() -> list[DispatcherEntry]:
    from hydromodpy.data.variables.recharge.config import RechargeSourceConfig

    return [
        DispatcherEntry(
            section_name="data",
            pattern="[[data.recharge.sources]]",
            model=RechargeSourceConfig,
            description=(
                "One recharge source entry. Multiple ``[[data.recharge.sources]]`` "
                "blocks are aggregated by the data manager."
            ),
        ),
    ]


def all_dispatchers() -> list[DispatcherEntry]:
    """Return every registered dispatcher entry."""
    entries: list[DispatcherEntry] = []
    for builder in (_flow_dispatchers, _data_dispatchers):
        try:
            entries.extend(builder())
        except Exception:
            continue
    return entries


def dispatchers_for_section(section_name: str) -> list[DispatcherEntry]:
    """Return dispatcher entries that decorate the page for ``section_name``."""
    return [entry for entry in all_dispatchers() if entry.section_name == section_name]


__all__ = ["DispatcherEntry", "all_dispatchers", "dispatchers_for_section"]
