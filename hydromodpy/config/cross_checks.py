"""The checks that cross a document with the flow solver it runs on, and the pairs of keys that spoil each other.

A document uses traits of the ``Model``: a boundary, an option of ``[solver]``, an
initial state, a sink or a source, the soil reservoir, the K tensor, the layering.
Each flow solver lists in ``supports`` the traits it honours. A trait the
document uses and its solver does not list would be ignored in the solve without
a word, so it is refused while the file is read, with the key the file wrote and
the solvers that honour it. The rule reads the registry and names no solver.

A transport solver reads products of the flow run it follows, and follows the
flow solvers its ``requires`` names. A product its flow does not write is
refused first, then a family its ``requires`` does not name. Two keys that
spoil each other whatever the solver are one row of ``CONTAMINATIONS``.

A sealed document, the frozen config of a run already on disk, is read as it ran:
every refusal here only warns there, so a run sealed before a refusal existed
still reads back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from typing import Any, get_args

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import resolve_simulation_time_grid
from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.domain.layers_config import (
    LAYERS,
    PASS_THROUGH,
    VerticalGridConfig,
    asks_for_layers,
)
from hydromodpy.model.forcing.soil_config import SOIL, soil_reservoir_of
from hydromodpy.model.initial.state import CyclicStart, PriorState, SteadyStart
from hydromodpy.model.initial_config import initial_state_of
from hydromodpy.model.model import ModelOptions
from hydromodpy.model.properties.property_table import (
    K_TENSOR,
    PROPERTIES,
    k_tensor_parameter_ids,
)
from hydromodpy.model.sinks_sources.container import (
    CUTOFF_WALL,
    ETP,
    FLOW_BARRIERS,
    RECHARGE,
    WELLS,
)
from hydromodpy.model.supports import INITIAL_STATE_TRAITS
from hydromodpy.solver.base.registry import solvers

logger = get_logger(__name__)

LAYERS_PATH = "domain.layers"
"""The key of the layering, in a file and in the overrides of a calibration phase."""


@dataclass(frozen=True)
class TraitUse:
    """How a document uses one trait of the ``Model``.

    ``where`` reads the validated document and returns what the file wrote to use
    the trait, as the refusal names it, or None when the document does not use it.
    """

    trait: str
    where: Callable[[Any], str | None]


def _boundary_use(bc_id: str) -> TraitUse:
    """The use of one boundary: active, through the table that declares it."""
    declared_at = FLOW_BOUNDARY_DEFINITIONS[bc_id].declared_at

    def where(cfg: Any) -> str | None:
        return declared_at if bc_id in cfg.flow.active_bc else None

    return TraitUse(bc_id, where)


def _option_use(name: str) -> TraitUse:
    """The use of one option of the ``Model``: a value other than the default of its key."""

    def where(cfg: Any) -> str | None:
        default = type(cfg.solver).model_fields[name].default
        return f"solver.{name}" if getattr(cfg.solver, name) != default else None

    return TraitUse(name, where)


def _initial_state_use(state: type, trait: str) -> TraitUse:
    """The use of one initial state: the state ``[flow.ic]`` asks for, or a restart."""
    if state is PriorState:
        return TraitUse(trait, lambda cfg: "flow.restart_from" if cfg.flow.restart_from else None)

    def where(cfg: Any) -> str | None:
        ic = cfg.flow.ic
        if getattr(ic, "h", None) is None or type(initial_state_of(ic)) is not state:
            return None
        return f"flow.ic.kind = {str(ic.h.kind)!r}"

    return TraitUse(trait, where)


def _sink_source_use(name: str) -> TraitUse:
    """The use of a sink or a source this run builds."""
    return TraitUse(
        name,
        lambda cfg: f"flow.sinks_sources.{name}" if name in cfg.flow.active_sinks_sources else None,
    )


def _flow_barriers(cfg: Any) -> str | None:
    return "flow.sinks_sources.flow_barriers" if cfg.flow.sinks_sources.enabled_barriers() else None


def _cutoff_walls(cfg: Any) -> str | None:
    lakes = cfg.flow.sinks_sources.enabled_lakes()
    walled = sorted(lake_id for lake_id, lake in lakes.items() if lake.cutoff_wall is not None)
    if not walled:
        return None
    return ", ".join(f"flow.sinks_sources.lakes.{lake_id}.cutoff_wall" for lake_id in walled)


def _soil(cfg: Any) -> str | None:
    return "flow.sinks_sources.recharge.soil" if soil_reservoir_of(cfg.flow) is not None else None


def _k_tensor(cfg: Any) -> str | None:
    ids = k_tensor_parameter_ids(cfg.flow.param or {})
    return ", ".join(f"flow.param.{param_id}" for param_id in ids) or None


def _properties(cfg: Any) -> str | None:
    """Name the table of aquifer properties the file wrote, ``flow.param`` first."""
    for owner, field in (("flow", "param"), ("domain", "depth_model")):
        section = getattr(cfg, owner, None)
        if field in getattr(section, "model_fields_set", frozenset()) and getattr(section, field):
            return f"{owner}.{field}"
    return None


def _layering_of_the_phase(
    layers: VerticalGridConfig, overrides: Mapping[str, Any]
) -> VerticalGridConfig | None:
    """Return the layering a calibration phase runs, with its ``domain.layers`` overrides.

    None when the phase writes no such override, or one that does not validate:
    the preflight names an override it cannot write.
    """
    written = {
        str(key): value
        for key, value in overrides.items()
        if key == LAYERS_PATH or str(key).startswith(f"{LAYERS_PATH}.")
    }
    if not written:
        return None
    table = written.pop(LAYERS_PATH, layers.model_dump(exclude_unset=True))
    if not isinstance(table, Mapping):
        return None
    payload = dict(table)
    payload.update({key.removeprefix(f"{LAYERS_PATH}."): value for key, value in written.items()})
    try:
        return VerticalGridConfig.model_validate(payload)
    except ValueError:
        return None


def _layerings(cfg: Any) -> list[tuple[str, VerticalGridConfig]]:
    """The layering of the file, then the one of each calibration phase that overrides it."""
    layers = cfg.domain.layers
    written = [(LAYERS_PATH, layers)]
    for phase in getattr(cfg.calibration, "phases", None) or ():
        phase_layers = _layering_of_the_phase(layers, getattr(phase, "overrides", None) or {})
        if phase_layers is not None:
            written.append(
                (f"the {LAYERS_PATH} override of calibration phase {phase.name!r}", phase_layers)
            )
    return written


def _layers(cfg: Any) -> str | None:
    asked = [
        f"{where} (genmtd_lay = {layers.genmtd_lay!r}, {layers.layer_count} layer(s))"
        for where, layers in _layerings(cfg)
        if asks_for_layers(layers)
    ]
    return ", ".join(asked) or None


def _pass_through(cfg: Any) -> str | None:
    return (
        f"{LAYERS_PATH}.pinch_out = 'pass_through'"
        if cfg.domain.layers.has_pass_through_cells
        else None
    )


TRAIT_USES: dict[str, TraitUse] = {
    use.trait: use
    for use in (
        *(_boundary_use(bc_id) for bc_id in FLOW_BOUNDARY_DEFINITIONS),
        *(_option_use(field.name) for field in fields(ModelOptions)),
        *(_initial_state_use(state, trait) for state, trait in INITIAL_STATE_TRAITS.items()),
        *(_sink_source_use(name) for name in (RECHARGE, WELLS, ETP)),
        TraitUse(FLOW_BARRIERS, _flow_barriers),
        TraitUse(CUTOFF_WALL, _cutoff_walls),
        TraitUse(SOIL, _soil),
        TraitUse(K_TENSOR, _k_tensor),
        TraitUse(PROPERTIES, _properties),
        TraitUse(LAYERS, _layers),
        TraitUse(PASS_THROUGH, _pass_through),
    )
}
"""How a document uses each trait a solver may list in ``supports``, one row per trait."""


def uses_of(cfg: Any) -> dict[str, str]:
    """Return each trait the document uses, with what the file wrote to use it."""
    uses: dict[str, str] = {}
    for trait, use in TRAIT_USES.items():
        where = use.where(cfg)
        if where is not None:
            uses[trait] = where
    return uses


def traits_of(cfg: Any) -> frozenset[str]:
    """Return the traits of the ``Model`` the document uses."""
    return frozenset(uses_of(cfg))


def flow_honors(cfg: Any, trait: str) -> bool:
    """Whether the flow solver of the document lists *trait* in its ``supports``."""
    return trait in solvers.get("flow", cfg.solver.backend_name).supports


def _honoring(trait: str) -> list[str]:
    """The flow solvers of this installation that list *trait* in their ``supports``."""
    return [name for name in solvers.names("flow") if trait in solvers.get("flow", name).supports]


def _refuse(message: str, error: type[Exception], *, sealed: bool) -> None:
    """Raise *message* as *error*, or only warn when the document is sealed."""
    if sealed:
        logger.warning("%s This sealed run is read as it ran.", message)
        return
    raise error(message)


def _flows_writing(product: str) -> list[str]:
    """The flow solvers of this installation that write *product*."""
    return [name for name in solvers.names("flow") if product in solvers.get("flow", name).writes]


def refuse_the_reads_the_flow_does_not_write(cfg: Any, *, sealed: bool) -> None:
    """Refuse a product a transport reads that the flow of the run does not write.

    A transport reads named products of the run it follows, ``face_flow`` above all.
    A flow solver that writes none of them cannot hand one over, so the run would read
    silence: refused while the file is read, with the key the file wrote, the transport,
    the product, and the flow solvers that write it. No solver is named in ``config/``.

    Raises
    ------
    IncompatibleCapabilitiesError
        Naming each missing product, the transport, and the flows that write it.
    """
    backend = cfg.solver.backend_name
    written = solvers.get("flow", backend).writes
    for process in cfg.simulation.process or ():
        if getattr(process, "kind", None) != "transport":
            continue
        for name in getattr(process, "solvers", None) or ():
            reads = solvers.get("transport", name).reads
            missing = sorted(str(product) for product in reads if product not in written)
            if not missing:
                continue
            product = missing[0]
            flows = _flows_writing(product)
            remedy = (
                f"Run the flow with a solver that writes it ({', '.join(flows)})."
                if flows
                else "No flow solver of this installation writes it."
            )
            _refuse(
                f"the transport solver {name!r} reads {', '.join(missing)}, and "
                f"solver.backend = {backend!r} does not write it. {remedy}",
                IncompatibleCapabilitiesError,
                sealed=sealed,
            )


def refuse_the_traits_the_solver_ignores(cfg: Any, *, sealed: bool) -> None:
    """Refuse each trait the document uses that its flow solver leaves out of ``supports``.

    Raises
    ------
    IncompatibleCapabilitiesError
        Naming each key the solver would ignore and the solvers that honour it.
    """
    backend = cfg.solver.backend_name
    supports = solvers.get("flow", backend).supports
    refusals: list[str] = []
    for trait, where in uses_of(cfg).items():
        if trait in supports:
            continue
        honoring = _honoring(trait)
        remedy = (
            f"run a flow solver that honors it ({', '.join(honoring)})"
            if honoring
            else "no flow solver of this installation honors it"
        )
        refusals.append(
            f"solver.backend = {backend!r} does not honor {where}: it would be ignored "
            f"without a word. Remove it, or {remedy}."
        )
    if refusals:
        _refuse(" ".join(refusals), IncompatibleCapabilitiesError, sealed=sealed)


def refuse_a_transport_its_flow_does_not_feed(cfg: Any, *, sealed: bool) -> None:
    """Refuse a transport solver whose ``requires`` does not name the flow solver of the run.

    A transport solver with an empty ``requires`` follows any flow.
    """
    backend = cfg.solver.backend_name
    for process in cfg.simulation.process or ():
        if getattr(process, "kind", None) != "transport":
            continue
        for name in getattr(process, "solvers", None) or ():
            requires = solvers.get("transport", name).requires
            flows = sorted(solver for kind, solver in requires if kind == "flow")
            if not flows or backend in flows:
                continue
            _refuse(
                f"the transport solver {name!r} follows {', '.join(flows)}, and "
                f"solver.backend is {backend!r}: it would read a flow it does not know. "
                "Remove the transport entry of [[simulation.process]], or run the flow "
                f"with {', '.join(flows)}.",
                ValueError,
                sealed=sealed,
            )


@dataclass(frozen=True)
class Contamination:
    """Two uses that spoil each other, whatever the solver.

    The pair applies when the document uses one trait of ``first`` and one of
    ``second``. ``message`` names them by what the file wrote, through the
    ``{first}`` and ``{second}`` fields, and says why and what to do.
    """

    first: frozenset[str]
    second: frozenset[str]
    message: str


CONTAMINATIONS: dict[str, Contamination] = {
    "restart_beside_a_computed_start": Contamination(
        first=frozenset({INITIAL_STATE_TRAITS[PriorState]}),
        second=frozenset({INITIAL_STATE_TRAITS[SteadyStart], INITIAL_STATE_TRAITS[CyclicStart]}),
        message=(
            "{first} is set and {second} computes its own initial heads, which would "
            "overwrite the restart without a message. Write a flow.ic that sets the heads, "
            "kind 'top' for instance, to start from the restart, or drop flow.restart_from "
            "to keep the computed start."
        ),
    ),
    "lake_under_a_cyclic_start": Contamination(
        first=frozenset({FLOW_BOUNDARY_DEFINITIONS["lake"].id}),
        second=frozenset({INITIAL_STATE_TRAITS[CyclicStart]}),
        message=(
            "{first} declares a lake and {second} repeats the run until the heads settle. "
            "The cycle carries the heads and not the lake stage, which starts again from "
            "initial_stage at each cycle. Run hmp spinup, which carries both from one cycle "
            "to the next, then start from its result with flow.restart_from."
        ),
    ),
}
"""The pairs of uses refused whatever the solver, one row per pair, with its reason."""


def refuse_the_contaminations(cfg: Any, *, sealed: bool) -> None:
    """Refuse each row of ``CONTAMINATIONS`` the document holds.

    Raises
    ------
    ValueError
        With the two keys the file wrote, why they spoil each other, and what to do.
    """
    uses = uses_of(cfg)
    for contamination in CONTAMINATIONS.values():
        first = next((uses[trait] for trait in sorted(contamination.first) if trait in uses), None)
        second = next(
            (uses[trait] for trait in sorted(contamination.second) if trait in uses), None
        )
        if first is not None and second is not None:
            _refuse(
                contamination.message.format(first=first, second=second), ValueError, sealed=sealed
            )


def warn_on_a_coarse_conductivity_profile(cfg: Any) -> None:
    """Warn when a vertical profile of K reaches a solver that cannot read it in full.

    A solver without ``layers`` reads one K per column. On fewer than five layers,
    one layer sums the profile up by K at mid-column: with H/d = 2.5 the
    transmissivity is off by -22 % to +75 % with the water table, and five equal
    layers bring it near -1 %.
    """
    backend = cfg.solver.backend_name
    one_layer = LAYERS not in solvers.get("flow", backend).supports
    layers = cfg.domain.layers
    for param_id, param in (cfg.flow.param or {}).items():
        profile = getattr(param, "field_vertical_profile", None)
        if str(param_id).lower() != "k" or profile is None or profile.kind == "none":
            continue
        if one_layer:
            logger.warning(
                "flow.param.%s has a vertical profile, and %s solves one layer and reads one "
                "K per column: the vertical profile below its sampling depth is not read.",
                param_id,
                backend,
            )
        elif layers.layer_count < 5:
            logger.warning(
                "flow.param.%s has a vertical profile and [domain.layers] builds %d "
                "layer(s). One layer sums the profile up by K at mid-column, off by "
                "-22 %% to +75 %% of the transmissivity at H/d = 2.5 as the water table "
                "moves; five equal layers bring it near -1 %%. Use at least five layers.",
                param_id,
                layers.layer_count,
            )


def refuse_a_native_step_finer_than_the_time_grid(cfg: Any, *, sealed: bool) -> None:
    """Refuse a flow solver that steps finer than a transient period of the run.

    A solver with a ``native_step`` advances several times inside a period the
    store keeps one value of: the ``Model`` feeds it the forcing of the period,
    so the extra steps would read the same forcing without a word. Refused while
    the file is read, with the key ``simulation.time.step_value``, the native
    step of the backend and the longest period of the grid. A period that stays
    permanent (the first of a transient run that says so, a steady run) stays
    out of the comparison.
    """
    backend = solvers.get("flow", cfg.solver.backend_name)
    native_step = getattr(backend, "native_step", None)
    if native_step is None:
        return
    step_seconds = _seconds_of_a_frequency_alias(native_step)
    if step_seconds is None:
        _refuse(
            f"the flow solver {cfg.solver.backend_name!r} advances on the native step "
            f"{native_step!r}, which is not a fixed frequency: the store keeps one "
            "value per period, so the run cannot check it against "
            "simulation.time.step_value. Give the backend a fixed frequency, or "
            "none.",
            IncompatibleCapabilitiesError,
            sealed=sealed,
        )
        return
    grid = resolve_simulation_time_grid(cfg)
    if grid is None:
        return
    lengths = list(grid.period_lengths_seconds)
    if str(getattr(cfg.flow, "flow_regime", "")) != "transient":
        return
    if getattr(cfg.flow, "first_period_steady", False) and len(lengths) > 1:
        lengths = lengths[1:]
    if not lengths:
        return
    longest = max(lengths)
    if step_seconds >= longest:
        return
    _refuse(
        f"the flow solver {cfg.solver.backend_name!r} advances on a native step of "
        f"{_seconds_text(step_seconds)}, finer than the longest transient period of "
        f"simulation.time.step_value ({longest:g} s): the store keeps one value "
        "per period, so the solver would read the same forcing at every step it "
        "takes inside the period. Give the run a period of one native step or "
        "finer, or drop the native step of the backend.",
        IncompatibleCapabilitiesError,
        sealed=sealed,
    )


def refuse_an_ignored_family_written(cfg: Any, *, sealed: bool) -> None:
    """Refuse a family the mesh engine ignores, written with another value than none.

    Read on ``model_fields_set``, so the default of ``[mesh.families]`` never
    refuses: only a key the file wrote, for a family its engine would skip
    without a word, is refused.
    """
    from hydromodpy.mesh.mesh_config import MeshFamiliesConfig
    from hydromodpy.mesh.registry import mesh_engines

    mesh = getattr(cfg, "mesh", None)
    if mesh is None:
        return
    ignored = mesh_engines.get(mesh.engine).capabilities.ignored_families
    written = set(getattr(mesh.families, "model_fields_set", ()) or ())
    for name in sorted(ignored & set(MeshFamiliesConfig.model_fields) & written):
        value = getattr(mesh.families, name)
        if value == "none":
            continue
        _refuse(
            f"[mesh.families] {name} = {value!r}, and the mesh engine "
            f"{mesh.engine!r} ignores it: the family would be skipped without a "
            'word. Set it to "none", or name an engine that meshes it.',
            IncompatibleCapabilitiesError,
            sealed=sealed,
        )


def refuse_a_point_method_under_a_lumped_mesh(cfg: Any, *, sealed: bool) -> None:
    """Refuse a point method written for the recharge or the ETP of a lumped mesh.

    Under a lumped engine a spatial source reads as ``area``, the mean over the
    one cell weighted by the shared area: the centre of the mesh is not a point
    that represents the rain of a catchment, and a nearest, linear or idw value
    would move with the shape of the outline. Read on ``model_fields_set``, so
    the default never refuses, and a file that writes nothing reads ``area``.
    """
    from hydromodpy.core.config_kit.types import InterpolationMethod
    from hydromodpy.mesh.registry import mesh_engines

    mesh = getattr(cfg, "mesh", None)
    if mesh is None or not mesh_engines.get(mesh.engine).capabilities.lumped:
        return
    point_methods = set(get_args(InterpolationMethod)) - {"area"}
    for name in (RECHARGE, ETP):
        section = getattr(cfg.flow.sinks_sources, name, None)
        if section is None or "interpolation_method" not in getattr(
            section, "model_fields_set", set()
        ):
            continue
        method = getattr(section, "interpolation_method", None)
        if method not in point_methods:
            continue
        _refuse(
            f"flow.sinks_sources.{name}.interpolation_method = {method!r}, and the "
            f"mesh engine {mesh.engine!r} meshes the catchment as one cell: a point "
            "method would read the forcing at its centre, which is not a point "
            'that represents it. Set "area", or name an engine that meshes cells.',
            IncompatibleCapabilitiesError,
            sealed=sealed,
        )


def deduce_the_mesh_engine(cfg: Any) -> None:
    """Write the mesh engine a global model reads, when the file writes none.

    Without an engine written the document would fall on the default, which a
    backend that only accepts lumped engines cannot read. When the backend
    accepts one engine and that engine meshes the catchment as one cell, the
    run takes it: the resolved config carries ``mesh.engine``, so the seal,
    the reader and the mesh step all see the engine the run took.
    """
    from hydromodpy.mesh.mesh_config import MeshConfig
    from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
    from hydromodpy.mesh.registry import mesh_engines

    mesh = getattr(cfg, "mesh", None)
    if mesh is not None and "engine" in mesh.model_fields_set:
        return
    accepted = getattr(solvers.get("flow", cfg.solver.backend_name), "accepted_meshes", ())
    if not accepted or ANY_PLANAR_ENGINE in accepted:
        return
    if len(set(accepted)) != 1:
        return  # several engines accepted: the document has to name one
    engine = next(iter(accepted))
    if not mesh_engines.get(engine).capabilities.lumped:
        return
    # Written through the instance, not assigned: the validation of the document
    # is already running. The engine is in the fields set of the new section, so
    # the resolved config writes it and a run that reads it back keeps it.
    if mesh is None:
        deduced = MeshConfig(engine=engine)
    else:
        deduced = mesh.model_copy(update={"engine": engine})
        deduced.__pydantic_fields_set__.add("engine")
    object.__setattr__(cfg, "mesh", deduced)


def _seconds_of_a_frequency_alias(alias: str) -> float | None:
    """Seconds of a fixed-frequency alias, ``None`` for a calendar one.

    Both spellings a document may write go through: the duration form a
    ``[simulation.time]`` step takes (``"30 day"``, ``"1.5 day"``, a
    ``pandas.Timedelta`` text), and the bare pandas aliases (``"D"``,
    ``"1.5D"``, ``"90 min"``). An anchored alias (``"MS"``, ``"W"``) is not a
    fixed frequency, so its length depends on the date it lands on, and this
    returns ``None``.
    """
    import pandas as pd

    text = str(alias).strip()
    try:
        return float(pd.Timedelta(text).total_seconds())
    except ValueError:
        pass
    try:
        offset = pd.tseries.frequencies.to_offset(text)
    except ValueError:
        return None
    try:
        return offset.nanos / 1e9
    except ValueError:
        # An anchored alias raises instead of carrying a nanos, so its length
        # depends on the date it lands on: not a fixed frequency.
        return None


def _seconds_text(seconds: float) -> str:
    """A duration in seconds, read back as a pandas Timedelta text."""
    import pandas as pd

    return str(pd.Timedelta(seconds=seconds))


def check_against_the_solver(cfg: Any, *, sealed: bool) -> None:
    """Run every check of this module on a validated document, in a fixed order.

    The traits the solver ignores come first, so a lake under a solver without
    lakes is named for that before any pair it belongs to. The products a
    transport reads are next, then the family its mesh engine ignores that the
    file wrote, then a point method under a lumped mesh, then a native step
    finer than a period, then the flows its requires names, then a pair of uses
    that spoil each other.
    """
    refuse_the_traits_the_solver_ignores(cfg, sealed=sealed)
    refuse_the_reads_the_flow_does_not_write(cfg, sealed=sealed)
    refuse_an_ignored_family_written(cfg, sealed=sealed)
    refuse_a_point_method_under_a_lumped_mesh(cfg, sealed=sealed)
    refuse_a_native_step_finer_than_the_time_grid(cfg, sealed=sealed)
    refuse_a_transport_its_flow_does_not_feed(cfg, sealed=sealed)
    refuse_the_contaminations(cfg, sealed=sealed)
    warn_on_a_coarse_conductivity_profile(cfg)


__all__ = [
    "CONTAMINATIONS",
    "Contamination",
    "TRAIT_USES",
    "TraitUse",
    "check_against_the_solver",
    "deduce_the_mesh_engine",
    "flow_honors",
    "refuse_a_transport_its_flow_does_not_feed",
    "refuse_a_native_step_finer_than_the_time_grid",
    "refuse_an_ignored_family_written",
    "refuse_a_point_method_under_a_lumped_mesh",
    "refuse_the_reads_the_flow_does_not_write",
    "refuse_the_contaminations",
    "refuse_the_traits_the_solver_ignores",
    "traits_of",
    "uses_of",
    "warn_on_a_coarse_conductivity_profile",
]
