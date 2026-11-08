"""The frozen ``Model`` every flow backend reads, and the functions that derive one model from another.

The ``prepare_solver`` step builds one ``Model`` per run with ``model_from_flow``,
from the ``Flow`` the setup and data steps bound, the mesh, the domain, the
delineation, the time grid and ``[solver]``. A backend reads it and nothing it
was built from, and never changes it: a solve leaves the ``Model`` as it found
it. ``steady_variant`` and ``cycle_variant`` give the model an auxiliary solve
runs on, ``with_initial`` and ``with_properties`` a model with one member set.

Each member keeps the object the ``Flow`` held, without a copy. A mapping is
read-only, a sequence is a tuple. The ``Model`` carries no configuration, no
delineation object, no folder and no setting of one backend.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Any

from hydromodpy.catchment.drainage.channel_tree import ChannelExits
from hydromodpy.core.time.steady_initialization import single_period_mean_forcing_time_grid
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.boundaries.boundary_condition_registry import (
    BoundaryConditionBundle,
    boundary_condition_bundle_from_flow,
)
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.geometry import CatchmentGeometry, RasterGeometry
from hydromodpy.model.flow import Flow
from hydromodpy.model.forcing.time_forcing import compact_pre_resolved_forcings
from hydromodpy.model.initial.state import (
    INITIAL_STATE_TYPES,
    HeadRule,
    InitialState,
    SolvedState,
    SteadyStart,
    SteadyStateStrategy,
)
from hydromodpy.model.initial_config import initial_state_of
from hydromodpy.model.properties.property_table import refuse_unknown_override_names
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.model.sinks_sources.wells import FlowWellConfig
from hydromodpy.model.time.regime import FlowRegime, normalize_flow_regime


def _frozen(mapping: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """A read-only mapping over a shallow copy: the values are the same objects."""
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True, slots=True, eq=False)
class Geometry:
    """Where the model lies.

    ``cells`` is the planar cell mesh MODFLOW 6 and Boussinesq build their grid
    on, and ``domain`` the vertical (top, base, layers, supports). ``raster``
    is the DEM grid NWT builds its grid on, and MODFLOW 6 reads it for the DEM
    its routing is conditioned on. ``catchment`` says where the catchment
    closes. ``channel_exits`` is the generated river network A read on the
    cells, which a backend turns into pinned receivers with its active columns
    and its lakes. A member the run does not have is ``None``.
    """

    cells: PlanarCellMesh | None
    domain: Domain | None
    raster: RasterGeometry | None = None
    catchment: CatchmentGeometry | None = None
    channel_exits: ChannelExits | None = None


@dataclass(frozen=True, slots=True, eq=False)
class Properties:
    """The hydraulic properties of the model.

    ``profiles`` maps a ``[flow.param]`` id to its ``FieldParam`` (K, Sy, Ss
    and the others), in SI with its vertical profile, in the declared order.
    Each backend samples them on its own grid through ``map_flow_properties``.
    ``overrides`` maps a property name to a value per cell set by
    ``Model.with_properties``. A backend passes it to
    ``resolve_flow_property_runtime_overrides`` with its grid, and it wins over
    the profiles.
    """

    profiles: Mapping[str, Any]
    overrides: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "profiles", _frozen(self.profiles))
        object.__setattr__(self, "overrides", _frozen(self.overrides))

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle the two mappings as dicts, which the constructor makes read-only again."""
        return (Properties, (dict(self.profiles), dict(self.overrides)))


@dataclass(frozen=True, slots=True, eq=False)
class ModelTime:
    """When the model runs.

    ``grid`` is the resolved time grid of ``[simulation.time]``, period
    lengths in seconds, or ``None`` for a steady run without one. ``regime``
    is ``steady`` or ``transient``. ``first_period_steady`` makes the first
    period of a transient run steady.
    """

    grid: Any
    regime: FlowRegime
    first_period_steady: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "regime", normalize_flow_regime(self.regime))

    @classmethod
    def from_flow(cls, flow: Flow, grid: Any) -> ModelTime:
        """The regime and the first period of a bound ``Flow`` on ``grid``."""
        return cls(grid=grid, regime=flow.flow_regime, first_period_steady=flow.first_period_steady)


@dataclass(frozen=True, slots=True)
class ModelOptions:
    """The four settings of ``[solver]`` that every backend reads the same way.

    ``sink_fill`` fills the DEM sinks before the top is sampled.
    ``drain_band_depth_m`` is the depth in metres of the band below the top
    where the drains sit. ``drain_bed_thickness_m`` is the thickness in metres
    of the drain bed, and ``drain_conductance_floor_m2_s`` the smallest drain
    conductance in m2/s.
    """

    sink_fill: bool
    drain_band_depth_m: float
    drain_bed_thickness_m: float
    drain_conductance_floor_m2_s: float

    @classmethod
    def from_settings(cls, solver: Any) -> ModelOptions:
        """Read the four settings off a ``[solver]`` section by name."""
        return cls(
            sink_fill=bool(solver.sink_fill),
            drain_band_depth_m=float(solver.drain_band_depth_m),
            drain_bed_thickness_m=float(solver.drain_bed_thickness_m),
            drain_conductance_floor_m2_s=float(solver.drain_conductance_floor_m2_s),
        )


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Model:
    """What a flow backend solves, frozen for the whole run.

    ``boundaries`` holds the typed ``[flow.bc]`` payloads and the active ids,
    with a read-only ``conditions``. ``recharge`` and ``etp`` are in m/s with
    their factor applied, and ``wells`` maps a well id to its payload with the
    flux in m3/s. ``lakes``, ``sfr`` and ``flow_barriers`` are the payloads the
    data step bound, by id. They keep the units the user wrote for
    ``bedleak`` (``bedleak_unit``), ``streambed_k`` (``streambed_k_unit``) and
    a barrier's ``hydchr``, ``k`` and ``thickness``, which MODFLOW 6 converts
    when it builds the package. ``active_sinks_sources`` lists the sink and
    source families the run builds. ``initial`` is one of the five start
    states of ``hydromodpy.model.initial.state``.
    """

    geometry: Geometry
    properties: Properties
    boundaries: BoundaryConditionBundle
    recharge: FlowRechargeConfig | None
    etp: FlowEtpConfig | None
    wells: Mapping[str, FlowWellConfig]
    lakes: Mapping[str, Mapping[str, Any]]
    sfr: Mapping[str, Mapping[str, Any]]
    flow_barriers: Mapping[str, Mapping[str, Any]]
    active_sinks_sources: tuple[str, ...]
    initial: InitialState
    time: ModelTime
    options: ModelOptions

    def __post_init__(self) -> None:
        for name in ("wells", "lakes", "sfr", "flow_barriers"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))
        object.__setattr__(self, "active_sinks_sources", tuple(self.active_sinks_sources))
        if not isinstance(self.boundaries.conditions, MappingProxyType):
            object.__setattr__(
                self,
                "boundaries",
                BoundaryConditionBundle(
                    conditions=_frozen(self.boundaries.conditions),
                    active_ids=tuple(self.boundaries.active_ids),
                ),
            )
        if not isinstance(self.initial, INITIAL_STATE_TYPES):
            raise TypeError(
                "Model.initial is one of "
                f"{', '.join(cls.__name__ for cls in INITIAL_STATE_TYPES)}; "
                f"got {type(self.initial).__name__}."
            )

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle the mappings as dicts, which the constructor makes read-only again.

        A read-only mapping does not pickle, and a worker of a parallel
        calibration sends the models of the solves it keeps over a pipe.
        """
        members = {member.name: getattr(self, member.name) for member in fields(self)}
        for name in ("wells", "lakes", "sfr", "flow_barriers"):
            members[name] = dict(members[name])
        members["boundaries"] = BoundaryConditionBundle(
            conditions=dict(self.boundaries.conditions),
            active_ids=self.boundaries.active_ids,
        )
        return (_rebuild_model, (members,))

    def with_properties(self, **values: Any) -> Model:
        """A new model whose per-cell overrides gain ``values``, by property name.

        The names are those ``resolve_flow_property_runtime_overrides`` reads:
        K, Kv, Sy, Ss, K22, angle1, angle2, angle3 or their output names. An
        other name is refused. A value is one number, one per planar cell or
        one per model cell. The backend checks its size and range on its grid.
        """
        refuse_unknown_override_names(values)
        merged = {**self.properties.overrides, **values}
        return replace(
            self, properties=Properties(profiles=self.properties.profiles, overrides=merged)
        )

    def with_initial(self, initial: InitialState) -> Model:
        """A new model that starts from ``initial``."""
        return replace(self, initial=initial)


def _rebuild_model(members: dict[str, Any]) -> Model:
    """The ``Model`` a pickle holds, built again by its constructor."""
    return Model(**members)


def _steady_recharge(
    recharge: FlowRechargeConfig | None, strategy: SteadyStateStrategy
) -> FlowRechargeConfig | None:
    """The recharge of a steady start: the time mean, or the prescribed rate on every period.

    A prescribed rate replaces the values too, because ``first_clim`` alone is
    read only for a sequence payload. It is written in the payload unit and
    drops a per-cell field, which would win over it.
    """
    if recharge is None:
        return None
    if strategy.rate_m_s is None:
        return recharge.model_copy(update={"first_clim": "mean"})
    payload_units = str(getattr(recharge, "units", "m/s") or "m/s")
    rate = strategy.rate_m_s / factor_to_m_per_s(payload_units)
    return recharge.model_copy(
        update={"values": rate, "first_clim": rate, "heterogeneous_source": None}
    )


def _averaged_over_periods(payloads: Mapping[str, Any], period_lengths: Any) -> Mapping[str, Any]:
    """The payloads with every per-period forcing replaced by its duration-weighted mean.

    The data step resolves lake and SFR forcings to one value per run period.
    The steady model has one period, so it reads their mean. The payloads are
    copied first, so the run's own model keeps its series.
    """
    if period_lengths is None or not payloads:
        return payloads
    averaged = copy.deepcopy(dict(payloads))
    compact_pre_resolved_forcings(averaged, period_lengths=list(period_lengths))
    return averaged


def steady_variant(model: Model, *, start: HeadRule | None = None) -> Model:
    """The model of the auxiliary steady solve, a new object.

    One period spanning the run (``single_period_mean_forcing_time_grid``), a
    steady regime, and the lake, SFR and barrier forcings averaged over the run
    periods. When ``model.initial`` is a ``SteadyStart`` the recharge follows
    its strategy, else it is unchanged, as for the first cycle of a spin-up
    that starts from the steady state. The solve starts from ``start``, the
    top by default for every backend.
    """
    lengths = getattr(model.time.grid, "period_lengths_seconds", None)
    recharge = model.recharge
    if isinstance(model.initial, SteadyStart):
        recharge = _steady_recharge(recharge, model.initial.strategy)
    return replace(
        model,
        time=ModelTime(
            grid=single_period_mean_forcing_time_grid(model.time.grid),
            regime="steady",
            first_period_steady=model.time.first_period_steady,
        ),
        recharge=recharge,
        lakes=_averaged_over_periods(model.lakes, lengths),
        sfr=_averaged_over_periods(model.sfr, lengths),
        flow_barriers=_averaged_over_periods(model.flow_barriers, lengths),
        initial=start if start is not None else HeadRule("top"),
    )


def cycle_variant(model: Model, seed: SolvedState | None) -> Model:
    """The model of one spin-up cycle, a new object that starts from ``seed`` or the top.

    Only the heads cycle. A lake starts each cycle from its ``initial_stage``.
    """
    return replace(model, initial=seed if seed is not None else HeadRule("top"))


def model_from_flow(
    flow: Flow,
    *,
    geometry: Geometry,
    time: ModelTime,
    options: ModelOptions,
    initial: InitialState | None = None,
) -> Model:
    """The ``Model`` of a bound ``Flow``, its members the objects the flow holds.

    ``initial`` defaults to the state ``[flow.ic]`` asks for. A restart passes
    the ``PriorState`` it read instead.
    """
    sinks_sources = flow.sinks_sources
    return Model(
        geometry=geometry,
        properties=Properties(profiles=flow.parameters),
        boundaries=boundary_condition_bundle_from_flow(flow),
        recharge=sinks_sources.get("recharge"),
        etp=sinks_sources.get("etp"),
        wells=sinks_sources.get("wells"),
        lakes=sinks_sources.get("lakes"),
        sfr=sinks_sources.get("sfr"),
        flow_barriers=sinks_sources.get("flow_barriers"),
        active_sinks_sources=tuple(flow.active_sinks_sources),
        initial=initial if initial is not None else initial_state_of(flow.initial_conditions),
        time=time,
        options=options,
    )


__all__ = [
    "Geometry",
    "Model",
    "ModelOptions",
    "ModelTime",
    "Properties",
    "cycle_variant",
    "model_from_flow",
    "steady_variant",
]
