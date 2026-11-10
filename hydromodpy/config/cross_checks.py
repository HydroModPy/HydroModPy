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

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from functools import cached_property
from typing import Any, get_args

from hydromodpy.core.exceptions import ConfigError, HydroModPyError, IncompatibleCapabilitiesError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.site import resolve_gauge
from hydromodpy.core.time import (
    grid_edges,
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
)
from hydromodpy.core.time.window import (
    build_simulation_time_boundaries,
    chain_windows,
    resolve_simulation_time_window,
)
from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.model.domain.layers_config import (
    LAYERS,
    PASS_THROUGH,
    VerticalGridConfig,
    asks_for_layers,
)
from hydromodpy.model.forcing.soil_config import (
    SOIL,
    soil_reservoir_of,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.model.forcing.validation import refuse_an_impossible_recharge
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


def _steady_rates_of_the_window(cfg: Any) -> list[str]:
    """The ``first_clim = "mean"`` keys a steady first period would average over a window."""
    if not getattr(cfg.flow, "first_period_steady", False):
        return []
    sinks = getattr(cfg.flow, "sinks_sources", None)
    averaged = []
    for name in ("recharge", "etp"):
        section = getattr(sinks, name, None)
        if section is not None and str(getattr(section, "first_clim", "mean")) == "mean":
            averaged.append(f"flow.sinks_sources.{name}.first_clim = 'mean'")
    return averaged


def refuse_a_window_chain_the_run_cannot_carry(cfg: Any, *, sealed: bool) -> None:
    """Refuse ``[simulation.time] window_length`` where a chain of windows would be wrong.

    A steady run has no period to cut. A chain of more than one window starts
    window 2 from the final state of window 1, which only a flow solver with the
    ``prior_state`` trait reads. No transport solver reads its concentrations
    back, so a transport would start window 2 from its first concentration. A
    calibration trial plays the whole simulation, so a window belongs to a run.
    A steady first period whose recharge or ETP is the mean of the periods would
    average the periods of window 1 only. Window 1 played alone reads no earlier
    state and passes the solver check.
    """
    time_config = getattr(cfg.simulation, "time", None)
    length = getattr(time_config, "window_length", None)
    if length is None:
        return
    regime = str(getattr(cfg.flow, "flow_regime", ""))
    if regime != "transient":
        _refuse(
            f"simulation.time.window_length = {length!r} cuts the stress periods of a "
            f"transient run, and flow.flow_regime is {regime!r}: a steady run has no period "
            "to cut. Remove window_length, or run the flow as transient.",
            ValueError,
            sealed=sealed,
        )
        return
    mode = getattr(getattr(cfg, "workflow", None), "mode", None)
    if mode == "calibration":
        _refuse(
            f"simulation.time.window_length = {length!r} cuts a run into windows, and "
            "workflow.mode = 'calibration' plays the whole simulation at every trial. "
            "Calibrate without window_length, then play the long run in windows.",
            ValueError,
            sealed=sealed,
        )
        return
    transports = [
        str(getattr(process, "id", "transport"))
        for process in cfg.simulation.process or ()
        if getattr(process, "kind", None) == "transport"
    ]
    if transports:
        _refuse(
            f"simulation.time.window_length = {length!r} cuts the run into windows, and "
            f"the transport {', '.join(transports)} would start every window from its first "
            "concentration: no transport solver reads its concentrations back. Remove the "
            "transport from [[simulation.process]], or run without window_length.",
            ValueError,
            sealed=sealed,
        )
        return
    grid = resolve_simulation_time_grid(cfg)
    try:
        count = len(chain_windows(grid, length))
    except ConfigError as exc:
        _refuse(str(exc), ValueError, sealed=sealed)
        return
    averaged = _steady_rates_of_the_window(cfg) if count > 1 else []
    if averaged:
        _refuse(
            f"simulation.time.window_length = {length!r} cuts the run into {count} windows, "
            "and flow.first_period_steady = true gives the first period of window 1 the mean "
            f"of {' and '.join(averaged)} over the periods of that window, not over the whole "
            "simulation, so the chain would not be the run in one piece. Set first_clim = "
            "'first' or a number, or set flow.first_period_steady = false and start from "
            "[flow.ic] kind = 'steady_state', which a chain computes over the whole simulation.",
            ValueError,
            sealed=sealed,
        )
        return
    chosen = getattr(time_config, "window", "all")
    chained = count > 1 if chosen == "all" else int(chosen) > 1
    trait = INITIAL_STATE_TRAITS[PriorState]
    if chained and not flow_honors(cfg, trait):
        _refuse(
            f"simulation.time.window_length = {length!r} starts each window after the first "
            "from the final state of the window before, and the flow solver "
            f"{cfg.solver.backend_name!r} does not read an earlier state ({trait}). Run the "
            f"chain with a flow solver that does ({', '.join(_honoring(trait))}), or play "
            "window 1 alone, or run without window_length.",
            IncompatibleCapabilitiesError,
            sealed=sealed,
        )


def coarse_conductivity_profile(cfg: Any, *, sealed: bool = False) -> list[str]:
    """Return the warnings of a vertical profile of K a solver cannot read in full.

    A solver without ``layers`` reads one K per column. On fewer than five layers,
    one layer sums the profile up by K at mid-column: with H/d = 2.5 the
    transmissivity is off by -22 % to +75 % with the water table, and five equal
    layers bring it near -1 %. A warning only, so ``sealed`` changes nothing.
    """
    backend = cfg.solver.backend_name
    one_layer = LAYERS not in solvers.get("flow", backend).supports
    layers = cfg.domain.layers
    said: list[str] = []
    for param_id, param in (cfg.flow.param or {}).items():
        profile = getattr(param, "field_vertical_profile", None)
        if str(param_id).lower() != "k" or profile is None or profile.kind == "none":
            continue
        if one_layer:
            said.append(
                f"flow.param.{param_id} has a vertical profile, and {backend} solves one "
                "layer and reads one K per column: the vertical profile below its sampling "
                "depth is not read."
            )
        elif layers.layer_count < 5:
            said.append(
                f"flow.param.{param_id} has a vertical profile and [domain.layers] builds "
                f"{layers.layer_count} layer(s). One layer sums the profile up by K at "
                "mid-column, off by -22 % to +75 % of the transmissivity at H/d = 2.5 as the "
                "water table moves; five equal layers bring it near -1 %. Use at least five "
                "layers."
            )
    return said


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


# ---------------------------------------------------------------------------
# The rules of the sections that read one another, whatever the solver
# ---------------------------------------------------------------------------

REAL_CATCHMENT_DEFINITIONS: frozenset[str] = frozenset(
    {"from_outlet_coord", "from_polyg_shp", "dem"}
)
"""Values of ``geographic.catchment.kind`` that model a real catchment, named by a site."""


def require_site_for_real_catchment(config: Any) -> None:
    """Refuse a real catchment that no site names.

    A run on a real catchment is grouped, compared and published by its site,
    never by the name of its project folder. A synthetic domain has no site,
    and a ``[sites]`` project takes the site of each case from its table row.
    Raises :class:`~hydromodpy.core.exceptions.ConfigError` naming
    ``catch_def`` and the key to write.
    """
    if getattr(config, "site", None) is not None or getattr(config, "sites", None) is not None:
        return
    geographic = getattr(config, "geographic", None)
    catch_def = getattr(geographic, "catch_def", None) if geographic is not None else None
    if catch_def not in REAL_CATCHMENT_DEFINITIONS:
        return
    raise ConfigError(
        f"geographic.catchment.kind = {catch_def!r} models a real catchment, and no "
        '[site] names it. Add [site] with name = "<catchment>" (letters, digits and '
        'underscores), and gauge = "<station>" when a station measures it.'
    )


def refuse_a_real_catchment_without_a_site(cfg: Any, *, sealed: bool) -> None:
    """Refuse a real catchment without [site].

    The rule holds for a file read from disk and for a Python caller alike.
    """
    try:
        require_site_for_real_catchment(cfg)
    except ConfigError as exc:
        raise ValueError(exc.message) from exc


def refuse_a_station_other_than_the_gauge(cfg: Any, *, sealed: bool) -> None:
    """Refuse a ``[metrics] station`` that is not the ``[site] gauge``.

    A sealed document is read as it was run, so ``[metrics] station`` is not checked.
    """
    if sealed:
        return
    try:
        resolve_gauge(cfg.site, getattr(cfg.metrics, "station", None), field="metrics.station")
    except ConfigError as exc:
        raise ValueError(exc.message) from exc


def refuse_site_and_sites_together(cfg: Any, *, sealed: bool) -> None:
    """Refuse a document that declares both ``[site]`` and ``[sites]``."""
    if cfg.site is not None and cfg.sites is not None:
        raise ValueError(
            "[site] and [sites] are both declared: a [sites] project takes the site "
            "of each case from its row of the site table. Remove [site], or remove "
            "[sites] to model one catchment."
        )


def refuse_a_metrics_window_outside_the_run(cfg: Any, *, sealed: bool) -> list[str]:
    """Refuse a ``[metrics] window`` that shares no day with ``[simulation.time]``.

    A sealed document, the frozen config of a run already on disk, is read
    as it was run: the window only warns, and the run has no score.
    """
    window = getattr(cfg.metrics, "window", None)
    run = cfg.simulation.time
    run_start = getattr(run, "start_datetime", None)
    run_end = getattr(run, "end_datetime", None)
    if window is None or run_start is None or run_end is None:
        return []
    if window.end >= run_start.date() and window.start <= run_end.date():
        return []
    missed = (
        f"[metrics] window runs from {window.start} to {window.end} and shares no "
        f"day with [simulation.time], which runs from {run_start.date()} to "
        f"{run_end.date()}"
    )
    if sealed:
        return [f"{missed}: this sealed run has no score."]
    raise ValueError(
        f"{missed}: the run would be scored on nothing. Move the window inside the "
        "run, or remove it."
    )


def refuse_an_overview_without_its_section(cfg: Any, *, sealed: bool) -> None:
    """Refuse ``workflow.mode = "overview"`` without an ``[overview]`` section."""
    if cfg.workflow.mode == "overview" and (cfg.overview is None):
        raise ValueError(
            "workflow.mode = 'overview' needs an [overview] section: it names the card and "
            "holds its window and panels. Add the section, with at least a name."
        )


def refuse_strict_inference_without_types(cfg: Any, *, sealed: bool) -> None:
    """Refuse ``data.inference_mode = "strict"`` with no explicit data type."""
    if cfg.data.inference_mode == "strict" and not cfg.data.types:
        raise ValueError(
            "data.inference_mode='strict' requires at least one explicit data type in data.types"
        )


def refuse_conditioning_choices_on_a_conditioned_dem(cfg: Any, *, sealed: bool) -> None:
    """Refuse the conditioning keys a conditioned DEM would ignore in silence.

    A DEM declared ``state = "conditioned"`` on a source of ``[data.dem]`` is
    routed as it is, so a written ``dem_resolution``, ``crossings.enabled``,
    ``dem_correc_type`` or ``capped_breach`` would be ignored and read as
    applied. Each written key is named, not just the first one.
    """
    if not _a_dem_source_is_conditioned(cfg.data):
        return
    geographic = getattr(cfg, "geographic", None)
    written: list[str] = []
    if geographic is not None:
        written_set = getattr(geographic, "model_fields_set", frozenset())
        if "dem_correc_type" in written_set:
            written.append("geographic.dem_correc_type")
        if "capped_breach" in written_set:
            written.append("geographic.capped_breach")
        catchment = getattr(geographic, "catchment", None)
        if catchment is not None and "dem_resolution" in getattr(
            catchment, "model_fields_set", frozenset()
        ):
            written.append("geographic.catchment.dem_resolution")
        crossings = getattr(geographic, "crossings", None)
        if crossings is not None and getattr(crossings, "enabled", False):
            written.append("geographic.crossings.enabled")
    if not written:
        return
    _refuse(
        "A DEM declared state = 'conditioned' is already conditioned, so "
        f"{', '.join(written)} would be ignored in silence. Remove the key, "
        "or declare the DEM as raw.",
        ConfigError,
        sealed=sealed,
    )


def _a_dem_source_is_conditioned(data_cfg: Any) -> bool:
    """Whether any source of ``[data.dem]`` declares ``state = "conditioned"``."""
    dem = getattr(data_cfg, "dem", None)
    for source in getattr(dem, "sources", ()) or ():
        state = (
            source.get("state") if isinstance(source, Mapping) else getattr(source, "state", None)
        )
        if state == "conditioned":
            return True
    return False


def refuse_a_raster_depth_without_its_substratum(cfg: Any, *, sealed: bool) -> None:
    """Refuse a raster depth model when ``[data.substratum]`` declares no raster."""
    depth_kind = cfg.domain.depth_model.kind
    if depth_kind in RASTER_DEPTH_MODEL_KINDS and cfg.data.substratum is None:
        raise ValueError(
            f"domain.depth_model kind = {depth_kind!r} reads the raster declared under "
            "[data.substratum]; declare it with one custom source."
        )


def refuse_a_river_mesh_without_a_threshold(cfg: Any, *, sealed: bool) -> None:
    """Refuse a mesh that needs the river network when no threshold is set.

    The mesh switches ``[geographic.river_network]`` on by itself, so the
    threshold check of that section never ran and the run stopped at
    ``build_geographic`` on a message that named neither the section nor the
    mesh. The rule is ``MeshConfig.requires_river_trace``, the one the
    geographic step reads.
    """
    geographic = cfg.geographic
    if geographic.uses_synthetic_geographic():
        return
    river_network = geographic.river_network
    if bool(river_network.enabled):
        return
    mesh = cfg.mesh
    if mesh is None:
        return
    active_bc = {str(name).lower() for name in cfg.flow.active_bc}
    if not mesh.requires_river_trace(active_bc=active_bc, synthetic=False):
        return
    if mesh.triangle is not None and mesh.triangle.path is not None:
        needed_by = "The 'stream' boundary on a [mesh.triangle] path mesh"
    elif mesh.families.rivers == "cell":
        needed_by = f"[mesh] engine = {mesh.engine!r} with families.rivers = 'cell'"
    else:
        needed_by = "[[mesh.refinement_zone]] where = 'height_above_stream'"
    refusal = river_network.missing_threshold_refusal(needed_by=needed_by)
    if refusal is not None:
        raise ValueError(refusal)


def refuse_a_calibration_without_parameters(cfg: Any, *, sealed: bool) -> None:
    """Refuse a ``[calibration]`` when ``flow.param_list`` names nothing to tune.

    A flow solver without field properties, such as a global model, calibrates
    its own solver options, so ``flow.param_list`` may stay empty under it.
    """
    if cfg.calibration is not None and flow_honors(cfg, PROPERTIES) and not cfg.flow.param_list:
        raise ValueError(
            "[calibration] requires flow.param_list to declare at least one tunable parameter"
        )


def refuse_the_soil_forcing_a_file_doubles_or_leaves_out(cfg: Any, *, sealed: bool) -> None:
    """Refuse a soil reservoir whose rain, ETP or discharge a data type loads twice or never."""
    if soil_reservoir_of(cfg.flow) is None:
        return
    data_cfg = cfg.data
    # data.types is read as declared here: recharge and runoff are never
    # inferred (data/loading/planner.py), so a fully-silent double count
    # would otherwise pass validation.
    declared_data_types = set(getattr(data_cfg, "types", []) or [])
    if "recharge" in declared_data_types:
        raise ValueError(
            "[flow.sinks_sources.recharge.soil] computes the recharge from "
            "the precipitation and the ETP, and data.types also loads one "
            "from [data.recharge]: the model would receive one and ignore "
            'the other. Remove "recharge" from data.types to keep the soil '
            "reservoir (and write recharge__delete = true under [data] if a "
            "base file declares it), or remove "
            "[flow.sinks_sources.recharge.soil] to use the loaded recharge."
        )
    if "runoff" in declared_data_types:
        raise ValueError(
            "[data.runoff] loads a surface runoff that already takes its "
            "share of the rain the soil reservoir receives (SIM2 RUNC, for "
            "instance): the streams, the lakes and the gauged discharge "
            'would count that water twice. Remove "runoff" from data.types '
            "(and write runoff__delete = true under [data] if a base file "
            "declares it); in soil mode the water that seeps out of "
            "saturated ground reaches the streams through the drains, and "
            "sealed ground through impervious_fraction."
        )
    if getattr(data_cfg, "precipitation", None) is None:
        raise ValueError(
            "[flow.sinks_sources.recharge.soil] fills the soil with daily "
            "precipitation, and no [data.precipitation] section says where "
            "to read it: add a [[data.precipitation.sources]] block, for "
            'example source = "sim2" with extent = "watershed".'
        )
    if getattr(data_cfg, "etp", None) is None:
        raise ValueError(
            "[flow.sinks_sources.recharge.soil] empties the soil with "
            "daily ETP, and no [data.etp] section says where to read it: "
            'add a [[data.etp.sources]] block, for example source = "sim2" '
            'with extent = "watershed".'
        )


def refuse_a_soil_recharge_that_cannot_reach_the_streams(cfg: Any, *, sealed: bool) -> None:
    """Refuse a soil reservoir switched off, or a lake its drains could not feed."""
    if soil_reservoir_of(cfg.flow) is None:
        return
    flow_cfg = cfg.flow
    active_sinks_sources = {
        str(name).lower() for name in getattr(flow_cfg, "active_sinks_sources", []) or []
    }
    if "recharge" not in active_sinks_sources:
        raise ValueError(
            "[flow.sinks_sources.recharge.soil] computes a recharge and its table "
            "says enabled = false, so MODFLOW would receive none: remove "
            "enabled = false, or remove the soil section."
        )

    soil_active_bc = {str(name).lower() for name in getattr(flow_cfg, "active_bc", []) or []}
    if "lake" in soil_active_bc and "sfr" not in soil_active_bc:
        raise ValueError(
            "[flow.sinks_sources.lakes] declares a lake with no stream network: in "
            "soil mode the water that seeps out of the ground reaches a lake "
            "only through the stream network, so the lake would receive "
            "none of it. Declare a [flow.sinks_sources.sfr] network, or remove "
            "[flow.sinks_sources.recharge.soil] and load [data.runoff] as before."
        )
    if "lake" in soil_active_bc:
        soil_sinks = getattr(flow_cfg, "sinks_sources", None)
        soil_sfr = getattr(soil_sinks, "sfr", None) or {}
        items = soil_sfr.items() if hasattr(soil_sfr, "items") else []
        for network_id, network in items:
            flag = (
                network.get("route_drainage", True)
                if isinstance(network, dict)
                else getattr(network, "route_drainage", True)
            )
            if flag is False:
                raise ValueError(
                    f"[flow.sinks_sources.sfr.{network_id}] sets route_drainage = "
                    "false with a lake and [flow.sinks_sources.recharge.soil]: the "
                    "water of the drains would leave the model and the lake would "
                    "receive only its own rain. Remove route_drainage = false "
                    "(it is on by default)."
                )


def refuse_soil_precipitation_in_parts(cfg: Any, *, sealed: bool) -> None:
    """Refuse a soil reservoir fed by a precipitation that loads more than ``total``."""
    if soil_reservoir_of(cfg.flow) is None:
        return
    for precip_source in getattr(getattr(cfg.data, "precipitation", None), "sources", []) or []:
        components = list(getattr(precip_source, "components", []) or [])
        if components != ["total"]:
            raise ValueError(
                f"[data.precipitation] loads components = {components!r}, "
                "and the soil reservoir takes one precipitation grid: two "
                "grids would be averaged, not added. Write "
                'components = ["total"], which counts the snow as rain.'
            )


class _TimeOfTheRun:
    """The window and the period boundaries of ``[simulation.time]``, built once.

    A walk of ``CROSS_RULES`` builds one and hands it to each rule that reads the
    time, so a run of 2 192 daily periods builds its boundaries once per walk and
    converts them to an index once. Nothing is kept past the walk, and a value
    that raises is raised again at each read.
    """

    def __init__(self, cfg: Any) -> None:
        self._cfg = cfg

    @cached_property
    def window(self) -> Any:
        """The resolved window, or ``None`` when the file has no ``[simulation.time]``."""
        return resolve_simulation_time_window(self._cfg)

    @cached_property
    def boundaries(self) -> list[Any] | None:
        """The half-open period boundaries of the window, or ``None`` without a window."""
        window = self.window
        return None if window is None else build_simulation_time_boundaries(window)

    @cached_property
    def edges(self) -> Any:
        """The boundaries as a checked tz-naive index, which ``grid_edges`` reads."""
        return grid_edges(self)


def refuse_a_soil_run_the_time_cannot_carry(
    cfg: Any, *, sealed: bool, time: _TimeOfTheRun | None = None
) -> None:
    """Refuse a soil reservoir without a daily window, a spin-up year, or a drained first period.

    *time* is the time of the run a walk of ``CROSS_RULES`` built once. Without
    it, the rule builds its own.
    """
    soil = soil_reservoir_of(cfg.flow)
    if soil is None:
        return
    time = _TimeOfTheRun(cfg) if time is None else time
    window = time.window
    if window is None:
        raise ValueError(
            "[flow.sinks_sources.recharge.soil] runs day by day over "
            "[simulation.time], which this file does not declare: add "
            "start_datetime, end_datetime and step_value."
        )

    boundaries = time.boundaries
    run_days = (boundaries[-1] - boundaries[0]).days
    spinup_message = spinup_refusal(soil, run_days)
    if spinup_message is not None:
        raise ValueError(spinup_message)

    steady_start_message = steady_start_refusal(cfg.flow, window)
    if steady_start_message is not None:
        raise ValueError(steady_start_message)


def refuse_a_recharge_the_model_would_not_read(cfg: Any, *, sealed: bool) -> None:
    """Refuse an impossible recharge rate, or one a loaded recharge replaces."""
    declared_recharge = getattr(cfg.flow.sinks_sources, "recharge", None)
    if declared_recharge is None:
        return
    refuse_an_impossible_recharge(
        declared_recharge.peak_rate_mm_day(),
        label="flow.sinks_sources.recharge.values",
    )
    if (
        soil_reservoir_of(cfg.flow) is None
        and "recharge" in set(getattr(cfg.data, "types", []) or [])
        and declared_recharge.peak_rate_mm_day() != 0.0
    ):
        raise ValueError(
            f"flow.sinks_sources.recharge.values = {declared_recharge.values!r} would be "
            "replaced by the series [data.recharge] loads, so the model would not read "
            "it: remove values (write values__delete = true if a base file declares "
            'it), or remove "recharge" from data.types to impose this rate.'
        )


def refuse_a_soil_capacity_without_the_soil(cfg: Any, *, sealed: bool) -> None:
    """Refuse ``[data.soil_capacity]`` when no soil reservoir reads it."""
    if soil_reservoir_of(cfg.flow) is None and getattr(cfg.data, "soil_capacity", None) is not None:
        raise ValueError(
            "[data.soil_capacity] is read only by the soil reservoir, and this "
            "file declares no [flow.sinks_sources.recharge.soil]: declare the "
            "soil section, or remove [data.soil_capacity]."
        )


def refuse_layer_bases_that_do_not_match(cfg: Any, *, sealed: bool) -> None:
    """Refuse a layering by surfaces whose rasters ``[data.layer_base]`` does not match.

    A layering by surfaces reads its rasters by name from ``[data.layer_base]``,
    and the two lists must match. What a solver reads of the layering is checked
    against its ``supports`` by ``refuse_the_traits_the_solver_ignores``.
    """
    layers = cfg.domain.layers
    layer_base = cfg.data.layer_base
    declared = set() if layer_base is None else {source.name for source in layer_base.sources}
    read = set(layers.base_surface_names)
    if read - declared:
        raise ValueError(
            f"[domain.layers] reads the base surfaces {sorted(read - declared)}, and "
            "[data.layer_base] does not declare them. Add one "
            "[[data.layer_base.sources]] entry per name, with its raster."
        )
    if declared - read:
        raise ValueError(
            f"[data.layer_base] declares {sorted(declared - read)}, and no layer of "
            "[domain.layers] reads them as its surface. Give a layer that surface, or "
            "remove the entries."
        )


def refuse_an_angle_with_a_depth_profile(cfg: Any, *, sealed: bool) -> None:
    """Refuse an angle of the K tensor with a depth profile.

    An angle is a direction: a vertical profile would scale it with depth,
    which has no meaning. Whether the solver reads the tensor at all is checked
    against its ``supports`` by ``refuse_the_traits_the_solver_ignores``.
    """
    params = cfg.flow.param or {}
    for param_id in k_tensor_parameter_ids(params):
        profile = getattr(params[param_id], "field_vertical_profile", None)
        if param_id.startswith("angle") and profile is not None and profile.kind != "none":
            raise ValueError(
                f"flow.param.{param_id} has a vertical profile, which would scale the "
                "angle with depth. Remove [flow.param."
                f"{param_id}.field_vertical_profile]; give the angle per zone instead."
            )


def refuse_a_solver_that_cannot_read_the_mesh(cfg: Any, *, sealed: bool) -> None:
    """Refuse a solver paired with a mesh engine whose cells it cannot read.

    Raised while the document is read, before any step of the pipeline runs.
    The engine is the one of ``[mesh]``, or ``regular`` when the section is
    absent. The rule is ``engine_accepted`` of the mesh registry.
    """
    from hydromodpy.mesh import registry as mesh_registry
    from hydromodpy.mesh.port import ANY_PLANAR_ENGINE

    mesh = cfg.mesh
    engine_id = mesh.engine if mesh is not None else mesh_registry.DEFAULT_ENGINE_ID
    solver_name = cfg.solver.backend_name
    accepted = solvers.get("flow", solver_name).accepted_meshes
    if mesh_registry.engine_accepted(accepted, engine_id):
        return
    names = ", ".join(sorted(accepted - {ANY_PLANAR_ENGINE}))
    if ANY_PLANAR_ENGINE in accepted:
        names += " and any engine with planar cells that is not lumped"
    readers = sorted(
        name
        for name in solvers.names("flow")
        if mesh_registry.engine_accepted(solvers.get("flow", name).accepted_meshes, engine_id)
    )
    origin = "" if mesh is not None and "engine" in mesh.model_fields_set else " (the default)"
    raise ValueError(
        f"solver {solver_name!r} reads the meshes of the engines {names}, and mesh.engine "
        f"is {engine_id!r}{origin}. Write [mesh] engine with one of the engines the solver "
        f"reads, or run a solver that reads {engine_id!r}"
        + (f" ({', '.join(readers)})." if readers else ".")
    )


def refuse_a_cell_address_on_an_irregular_mesh(cfg: Any, *, sealed: bool) -> None:
    """Refuse a ``[lay, row, col]`` address when the mesh has no rows and columns.

    A well (``location.kind = "cell"``) or an explicit SFR reach
    (``reaches[].cell``) names its cell by layer, row and column. Only the
    ``regular`` engine has rows and columns: on a triangle or Voronoi mesh the
    address names no cell, and the build would stop on it after meshing. The
    engine is the one of ``[mesh]``, or ``regular`` when the section is absent.
    """
    from hydromodpy.mesh import registry as mesh_registry

    mesh = cfg.mesh
    engine_id = mesh.engine if mesh is not None else mesh_registry.DEFAULT_ENGINE_ID
    if engine_id == "regular":
        return
    sinks_sources = cfg.flow.sinks_sources
    addressed: list[str] = []
    for well_id, well in (getattr(sinks_sources, "wells", None) or {}).items():
        if getattr(getattr(well, "location", None), "kind", None) == "cell":
            addressed.append(f"flow.sinks_sources.wells.{well_id}.location")
    for network_id, network in (getattr(sinks_sources, "sfr", None) or {}).items():
        for index, reach in enumerate(getattr(network, "reaches", None) or []):
            if getattr(getattr(reach, "cell", None), "kind", None) == "cell":
                addressed.append(f"flow.sinks_sources.sfr.{network_id}.reaches[{index}].cell")
    if addressed:
        raise ValueError(
            f"A cell is addressed by [lay, row, col] at {', '.join(addressed)}, and "
            f"mesh.engine is {engine_id!r}: only the 'regular' engine has rows and "
            "columns. Locate a well by coordinates (absolute_xy or relative_xy), or "
            'write [mesh] engine = "regular".'
        )


# ---------------------------------------------------------------------------
# The rules of ``[[export]]`` and ``[display]`` against the run
# ---------------------------------------------------------------------------


def _time_grid(cfg: object, time: _TimeOfTheRun) -> tuple[Any, int] | None:
    """Return the period edges and the period count of the run, or None if undecidable.

    The store holds one record per stress period, so the grid
    ``[simulation.time]`` resolves to is what a date or an index is read
    against. Only the boundaries are built, once per walk, and the period
    lengths a solver reads are left to the run. ``None`` is returned rather
    than a guess when the grid does not resolve here: a config whose window is
    refused by another validator further down. A missed check costs a late
    error; a wrong grid would refuse a run that is correct.
    """
    try:
        boundaries = time.boundaries
    except ValueError:
        # The window itself is malformed. It has its own message, raised where
        # the grid is built for real; shadowing it here would say the wrong thing.
        return None
    if boundaries is None:
        # No [simulation.time]: a steady flow run has one period and no dates.
        try:
            grid = require_flow_simulation_time_grid(cfg)
        except ValueError:
            return None
        if grid is None:
            return None
        nper = int(getattr(grid, "nper", 0))
        return (grid_edges(grid), nper) if nper >= 1 else None
    nper = len(boundaries) - 1
    if nper < 1:
        return None
    try:
        edges = time.edges
    except ValueError:
        # Boundaries that do not increase: the run refuses them where it builds its periods.
        return None
    return edges, nper


def _time_selectors(cfg: object) -> list[tuple[str, str, Any]]:
    """Return every ``(where, kind, selector)`` a config reads a time with.

    ``kind`` is ``"instant"`` for one selector, ``"dates"`` for a list of them
    and ``"period"`` for a ``(start, end)`` pair. The ``[[export]]`` blocks give
    ``time`` and ``period``; ``[display]`` gives ``time``, and so can the options
    of each figure under ``[display.overrides.<figure>]``.
    """
    selectors: list[tuple[str, str, Any]] = []
    for index, request in enumerate(getattr(cfg, "export", None) or ()):
        selectors.append((f"export[{index}].time", "dates", request.times))
        if request.period is not None:
            selectors.append((f"export[{index}].period", "period", request.period))
    display = getattr(cfg, "display", None)
    display_time = getattr(display, "time", None)
    if display_time is not None:
        selectors.append(("display.time", "instant", display_time))
    for figure, options in (getattr(display, "overrides", None) or {}).items():
        if isinstance(options, dict) and options.get("time") is not None:
            selectors.append((f"display.overrides.{figure}.time", "instant", options["time"]))
    return selectors


def refuse_a_time_the_run_does_not_hold(
    cfg: Any, *, sealed: bool, time: _TimeOfTheRun | None = None
) -> None:
    """Refuse a date or a step the run will not hold.

    Reads every time selector of ``[[export]]`` and ``[display]`` against the
    stress periods ``[simulation.time]`` resolves to: a date outside the
    record, a date on a steady run without a window, a step index past the
    end, two dates of one list that read the same period. The mistake costs
    nothing: no solve is paid for before it is caught. *time* is the time of
    the run a walk of ``CROSS_RULES`` built once. Without it, the rule builds
    its own.
    """
    from hydromodpy.core.time import (
        TimeSelectionError,
        resolve_instant,
        resolve_instants,
        resolve_period,
    )

    selectors = _time_selectors(cfg)
    if not selectors:
        return
    grid = _time_grid(cfg, _TimeOfTheRun(cfg) if time is None else time)
    if grid is None:
        return
    edges, nper = grid
    count = None if edges is not None else nper
    refused: list[str] = []
    for where, kind, selector in selectors:
        try:
            if kind == "period":
                resolve_period(selector[0], selector[1], edges, n_periods=count)
            elif kind == "dates":
                resolve_instants(selector, edges, n_periods=count)
            else:
                resolve_instant(selector, edges, n_periods=count)
        except TimeSelectionError as exc:
            refused.append(f"  {where}: {exc}")
    if refused:
        _refuse(
            "a time names no stress period of this run "
            f"([simulation.time] resolves to {nper} period{'s' if nper > 1 else ''}):\n"
            + "\n".join(refused),
            ConfigError,
            sealed=sealed,
        )


_UNKNOWN_RUN_LABEL = "\0run"
"""The run name a file of several variables is planned under before the run exists.

The real stem is the name of the run directory, which a document does not hold.
A NUL byte is in no path a file system takes, so a planned stem never meets a
``file`` or a single name written in a block. Two blocks that both write the
stem of the run still meet, whatever the run is called. A ``file`` that takes
the name of the run is refused at the start of the export instead.
"""


def refuse_an_export_that_cannot_be_written(cfg: Any, *, sealed: bool) -> None:
    """Refuse an ``[[export]]`` block that cannot be written.

    Every name is looked up in the vocabulary of what a run can export, and
    each block is planned file by file with the kind of each name. A name no
    run can hold, a kind the format cannot carry, a ``crs`` or ``resolution``
    no file takes, a ``file`` that would be several files, and two blocks
    writing one file are refused, each naming its block (``export[2]``).
    """
    from hydromodpy.results.exporters.export_spec import plan_outputs
    from hydromodpy.results.exporters.vocabulary import describe_export_names, export_kind

    requests = list(getattr(cfg, "export", None) or ())
    if not requests:
        return
    unknown = [
        f"export[{index}]: {name!r}"
        for index, request in enumerate(requests)
        for name in request.names
        if export_kind(name) is None
    ]
    if unknown:
        _refuse(
            f"no run can export {', '.join(unknown)}. The names a run can export:\n"
            f"{describe_export_names()}\n"
            "'hmp export <run> --list' prints the ones a given run holds.",
            ConfigError,
            sealed=sealed,
        )
        return
    writers: dict[str, int] = {}
    for index, request in enumerate(requests):
        kinds = {name: export_kind(name) for name in request.names}
        try:
            planned = plan_outputs(request, kinds, run_label=_UNKNOWN_RUN_LABEL)
        except ValueError as exc:
            _refuse(f"export[{index}]: {exc}", ConfigError, sealed=sealed)
            return
        for item in planned:
            path = str(item.path)
            first = writers.setdefault(path, index)
            if first != index:
                path = path.replace(_UNKNOWN_RUN_LABEL, "<run>")
                _refuse(
                    f"export[{first}] and export[{index}] both write {path}. Give one of "
                    "them its own file or folder.",
                    ConfigError,
                    sealed=sealed,
                )
                return


@dataclass(frozen=True)
class CrossRule:
    """One rule that reads several validated sections together.

    ``reads`` names the root sections the rule reads, so the check of a draft runs
    it only once each of them is complete. ``rule(sections, *, sealed)`` reads the
    sections as attributes, raises a ``ValueError`` or a typed error on a
    refusal, and returns the warnings it gives. ``code`` is the check code of its
    refusal. The name of the rule is the name of its function.
    """

    rule: Callable[..., Iterable[str] | None]
    reads: frozenset[str]
    code: str = "cross_rule"
    reads_the_time: bool = False
    """True hands the rule, as ``time``, the window and the boundaries the walk builds once."""

    @property
    def name(self) -> str:
        return self.rule.__name__


@dataclass(frozen=True)
class RuleOutcome:
    """What one rule said of a document: its refusal, or its warnings."""

    rule: CrossRule
    error: Exception | None = None
    warnings: tuple[str, ...] = ()


def _reads(*sections: str) -> frozenset[str]:
    return frozenset(sections)


_SOLVER_AND_TRAITS = _reads("solver", "flow", "domain", "calibration")

CROSS_RULES: dict[str, CrossRule] = {
    rule.name: rule
    for rule in (
        CrossRule(refuse_a_real_catchment_without_a_site, _reads("geographic", "site", "sites")),
        CrossRule(refuse_a_station_other_than_the_gauge, _reads("site", "metrics")),
        CrossRule(refuse_site_and_sites_together, _reads("site", "sites")),
        CrossRule(refuse_a_metrics_window_outside_the_run, _reads("metrics", "simulation")),
        CrossRule(refuse_an_overview_without_its_section, _reads("workflow", "overview")),
        CrossRule(refuse_strict_inference_without_types, _reads("data")),
        CrossRule(refuse_conditioning_choices_on_a_conditioned_dem, _reads("data", "geographic")),
        CrossRule(refuse_a_raster_depth_without_its_substratum, _reads("domain", "data")),
        CrossRule(refuse_a_river_mesh_without_a_threshold, _reads("geographic", "mesh", "flow")),
        CrossRule(refuse_a_calibration_without_parameters, _reads("calibration", "flow", "solver")),
        # What the flow solver ignores is named before the checks of one section,
        # and the traits it ignores come first, so a lake under a solver without
        # lakes is named for that before any pair it belongs to.
        CrossRule(refuse_the_traits_the_solver_ignores, _SOLVER_AND_TRAITS, "incompatible"),
        CrossRule(
            refuse_the_reads_the_flow_does_not_write, _reads("solver", "simulation"), "incompatible"
        ),
        CrossRule(refuse_an_ignored_family_written, _reads("mesh"), "incompatible"),
        CrossRule(
            refuse_a_point_method_under_a_lumped_mesh, _reads("mesh", "flow"), "incompatible"
        ),
        CrossRule(
            refuse_a_native_step_finer_than_the_time_grid,
            _reads("solver", "simulation", "flow"),
            "incompatible",
        ),
        CrossRule(refuse_a_transport_its_flow_does_not_feed, _reads("solver", "simulation")),
        CrossRule(refuse_the_contaminations, _SOLVER_AND_TRAITS, "contamination"),
        CrossRule(
            refuse_a_window_chain_the_run_cannot_carry,
            _reads("simulation", "flow", "solver", "workflow"),
            "incompatible",
        ),
        CrossRule(coarse_conductivity_profile, _reads("solver", "domain", "flow")),
        CrossRule(refuse_the_soil_forcing_a_file_doubles_or_leaves_out, _reads("flow", "data")),
        CrossRule(refuse_a_soil_recharge_that_cannot_reach_the_streams, _reads("flow")),
        CrossRule(refuse_soil_precipitation_in_parts, _reads("flow", "data")),
        CrossRule(
            refuse_a_soil_run_the_time_cannot_carry,
            _reads("flow", "simulation"),
            reads_the_time=True,
        ),
        CrossRule(refuse_a_recharge_the_model_would_not_read, _reads("flow", "data")),
        CrossRule(refuse_a_soil_capacity_without_the_soil, _reads("flow", "data")),
        CrossRule(refuse_layer_bases_that_do_not_match, _reads("domain", "data")),
        CrossRule(refuse_an_angle_with_a_depth_profile, _reads("flow")),
        # Last, so a fault of the solver itself is named before a mesh it would not read.
        CrossRule(refuse_a_solver_that_cannot_read_the_mesh, _reads("solver", "mesh")),
        CrossRule(refuse_a_cell_address_on_an_irregular_mesh, _reads("mesh", "flow")),
        # What a run would refuse at its first step, so a mistake costs no solve.
        CrossRule(
            refuse_a_time_the_run_does_not_hold,
            _reads("export", "display", "simulation", "flow"),
            reads_the_time=True,
        ),
        CrossRule(refuse_an_export_that_cannot_be_written, _reads("export")),
    )
}
"""The rules that read several sections of a validated document, in the order they run.

The validator of the root walks them, and the loader and the check run them all
and keep every refusal. A new rule is one row here, with the sections it reads.
"""


def run_cross_rules(
    sections: Any,
    *,
    sealed: bool,
    ready: Callable[[CrossRule], bool] | None = None,
    first_only: bool = False,
) -> list[RuleOutcome]:
    """Run each row of ``CROSS_RULES`` on *sections*, in order, and return what each said.

    *sections* is the built document, or any object that holds the validated
    sections as attributes. *ready* skips a rule whose sections are not complete
    yet. *first_only* stops at the first refusal, as a validator does. The time
    of the run is built once for the walk, and only if a rule reads it.
    """
    outcomes: list[RuleOutcome] = []
    time = _TimeOfTheRun(sections)
    for rule in CROSS_RULES.values():
        if ready is not None and not ready(rule):
            continue
        given = {"time": time} if rule.reads_the_time else {}
        try:
            said = tuple(rule.rule(sections, sealed=sealed, **given) or ())
        except (ValueError, HydroModPyError) as exc:
            outcomes.append(RuleOutcome(rule, error=exc))
            if first_only:
                break
            continue
        outcomes.append(RuleOutcome(rule, warnings=said))
    return outcomes


def check_against_the_solver(cfg: Any, *, sealed: bool) -> None:
    """Run every row of ``CROSS_RULES`` on a validated document, and raise the first refusal.

    The rows are the checks against the flow solver and the rules between sections.
    A warning of a rule is logged as it comes, so a rule after a refusal says nothing.
    """
    for outcome in run_cross_rules(cfg, sealed=sealed, first_only=True):
        for text in outcome.warnings:
            logger.warning("%s", text)
        if outcome.error is not None:
            raise outcome.error


__all__ = [
    "CONTAMINATIONS",
    "CROSS_RULES",
    "Contamination",
    "CrossRule",
    "REAL_CATCHMENT_DEFINITIONS",
    "RuleOutcome",
    "TRAIT_USES",
    "TraitUse",
    "coarse_conductivity_profile",
    "deduce_the_mesh_engine",
    "flow_honors",
    "refuse_a_calibration_without_parameters",
    "refuse_a_cell_address_on_an_irregular_mesh",
    "refuse_a_metrics_window_outside_the_run",
    "refuse_a_native_step_finer_than_the_time_grid",
    "refuse_a_point_method_under_a_lumped_mesh",
    "refuse_a_raster_depth_without_its_substratum",
    "refuse_a_real_catchment_without_a_site",
    "refuse_a_recharge_the_model_would_not_read",
    "refuse_a_river_mesh_without_a_threshold",
    "refuse_a_soil_capacity_without_the_soil",
    "refuse_a_soil_recharge_that_cannot_reach_the_streams",
    "refuse_a_soil_run_the_time_cannot_carry",
    "refuse_a_solver_that_cannot_read_the_mesh",
    "refuse_a_station_other_than_the_gauge",
    "refuse_a_time_the_run_does_not_hold",
    "refuse_a_transport_its_flow_does_not_feed",
    "refuse_a_window_chain_the_run_cannot_carry",
    "refuse_conditioning_choices_on_a_conditioned_dem",
    "refuse_an_angle_with_a_depth_profile",
    "refuse_an_export_that_cannot_be_written",
    "refuse_an_ignored_family_written",
    "refuse_an_overview_without_its_section",
    "refuse_layer_bases_that_do_not_match",
    "refuse_site_and_sites_together",
    "refuse_soil_precipitation_in_parts",
    "refuse_strict_inference_without_types",
    "refuse_the_contaminations",
    "refuse_the_reads_the_flow_does_not_write",
    "refuse_the_soil_forcing_a_file_doubles_or_leaves_out",
    "refuse_the_traits_the_solver_ignores",
    "require_site_for_real_catchment",
    "run_cross_rules",
    "traits_of",
    "uses_of",
    "check_against_the_solver",
]
