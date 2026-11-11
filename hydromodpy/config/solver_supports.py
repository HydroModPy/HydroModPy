"""What the solver supports: trait uses, flow and transport refusals, time-window and native-step refusals, the mesh engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from typing import Any, get_args

from hydromodpy.core.exceptions import ConfigError, IncompatibleCapabilitiesError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.window import chain_windows, resolve_simulation_time_grid
from hydromodpy.model.boundaries.boundary_condition_registry import FLOW_BOUNDARY_DEFINITIONS
from hydromodpy.model.domain.layers_config import (
    LAYERS,
    PASS_THROUGH,
    VerticalGridConfig,
    asks_for_layers,
)
from hydromodpy.model.forcing.soil_config import (
    SOIL,
    soil_reservoir_of,
)
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
from hydromodpy.results.field_registry import FACE_FLOW
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


def flow_honors(cfg: Any, trait: str) -> bool:
    """Whether the flow solver of the document lists *trait* in its ``supports``."""
    return trait in solvers.get("flow", cfg.solver.backend_name).supports


def _honoring(trait: str) -> list[str]:
    """The flow solvers of this installation that list *trait* in their ``supports``."""
    return [name for name in solvers.names("flow") if trait in solvers.get("flow", name).supports]


def refuse(message: str, error: type[Exception], *, sealed: bool) -> None:
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
            refuse(
                f"the transport solver {name!r} reads {', '.join(missing)}, and "
                f"solver.backend = {backend!r} does not write it. {remedy}",
                IncompatibleCapabilitiesError,
                sealed=sealed,
            )


def refuse_face_flows_the_flow_does_not_write(cfg: Any, *, sealed: bool) -> None:
    """Refuse ``keep_face_flows`` when the flow of the run does not write it.

    A run that keeps the flow between cells asks the flow solver for
    ``face_flow``. A solver that does not write it keeps nothing, so the run
    stops while the file is read and names the solvers that write it.

    Raises
    ------
    IncompatibleCapabilitiesError
        Naming the backend and the flow solvers that write ``face_flow``.
    """
    if not cfg.simulation.results.keep_face_flows:
        return
    backend = cfg.solver.backend_name
    if FACE_FLOW in solvers.get("flow", backend).writes:
        return
    flows = _flows_writing(FACE_FLOW)
    remedy = (
        f"Run the flow with a solver that writes it ({', '.join(flows)}), or set "
        "keep_face_flows = false."
        if flows
        else "No flow solver of this installation writes it; set keep_face_flows = false."
    )
    refuse(
        "[simulation.results] keep_face_flows = true keeps the flow between cells, "
        f"and solver.backend = {backend!r} does not write it. {remedy}",
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
        refuse(" ".join(refusals), IncompatibleCapabilitiesError, sealed=sealed)


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
            refuse(
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
            refuse(
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
        refuse(
            f"simulation.time.window_length = {length!r} cuts the stress periods of a "
            f"transient run, and flow.flow_regime is {regime!r}: a steady run has no period "
            "to cut. Remove window_length, or run the flow as transient.",
            ValueError,
            sealed=sealed,
        )
        return
    mode = getattr(getattr(cfg, "workflow", None), "mode", None)
    if mode == "calibration":
        refuse(
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
        refuse(
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
        refuse(str(exc), ValueError, sealed=sealed)
        return
    averaged = _steady_rates_of_the_window(cfg) if count > 1 else []
    if averaged:
        refuse(
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
        refuse(
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
        refuse(
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
    refuse(
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
        refuse(
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
        refuse(
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
