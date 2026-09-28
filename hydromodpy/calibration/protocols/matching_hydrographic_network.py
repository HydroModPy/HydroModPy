"""The two-stage calibration against the mapped hydrographic network.

Where a gauge gives one series at one point, the mapped stream network gives a
spatial constraint over the whole catchment: the extent of the network the
aquifer keeps flowing is set by how much water the medium transmits, so the
agreement between the simulated seepage network and the mapped one identifies
K/R, the ratio of conductivity to recharge, without any discharge record at
all; the conductivity itself follows once R is fixed. The storage coefficient
neither network can see is then read from the hydrograph, at that conductivity
held fixed.

Stage one is :cite:`abherve2023`. Stage two, reading the specific yield from
the observed hydrograph with the conductivity frozen, is
:cite:`abherve2025climate`'s application of the method. :cite:`abherve2024headwater`
also calibrates against streamflow intermittence, but its own abstract
describes a simultaneous K-and-porosity calibration validated against ONDE,
not this sequential two-stage method, so it is not cited here as a second
application of stage two.

Stage one is steady: one period over the record, the mean recharge, and the
conductivity moved until the simulated network matches the mapped one. Stage two
is transient at the forcing step, the conductivity frozen, and the storage moved
against the observed hydrograph. The order is not a convenience. A steady solve
carries no storage, so stage one is blind to it, which is exactly what makes the
ratio identifiable there.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pandas as pd

from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions, outputs_agree
from hydromodpy.calibration.protocols.base import Deviation, Reference

STEADY_STAGE = "steady_conductivity"
TRANSIENT_STAGE = "transient_storage"
NETWORK_BLOCK = "network_extension"
HYDROGRAPH_OUTPUT = "hydrograph"
HYDROGRAPH_BLOCK = "hydrograph"


class MatchingHydrographicNetwork:
    """Conductivity from the mapped stream network, storage from the hydrograph."""

    name = "matching_hydrographic_network"
    version = "1.2"
    """Bumped from 1.1, which v2.0.0a1 released. Three defaults moved, and each
    changes the result of a file re-run without a pin: the DEM is filled rather
    than breached before the catchment is cut ([geographic].dem_correc_type),
    the transient stage leaves the first year of the run out as spin-up, and
    the bound of Eq. 4 is a length in metres (validity_length = 'auto') where
    it was roptim_max = 2 on a ratio to the cell size.

    Bumped from 1.0 to 1.1: the descent used to build the criterion defaulted
    to D8, and the validity bound of Eq. 4 was read only at the point the
    search returns rather than at every trial.

    A pin on an older version is refused rather than silently upgraded.
    """
    title = "Matching the hydrographic network"
    summary = (
        "Two stages. The mapped stream network constrains K/R, the ratio of "
        "hydraulic conductivity to recharge, in steady state (Abherve et al., "
        "2023), by balancing the descent from the simulated seepage network to "
        "the mapped one against its reciprocal. The specific yield, to which a "
        "steady solve is blind, is then read from the observed hydrograph with "
        "the conductivity frozen (Abherve et al., 2025). The first stage needs "
        "no discharge record."
    )
    stages = (
        "Steady state, mean recharge over the record: move the conductivity until the "
        "simulated seepage network matches the mapped one.",
        "Transient at the forcing step, conductivity frozen: move the specific yield "
        "against the observed hydrograph, scored after the first year of the run, the "
        "spin-up, unless the file declares a scoring window.",
    )
    references = (
        Reference(
            key="abherve2023",
            authors="Abherve, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., "
            "Aquilina, L., de Dreuzy, J.-R.",
            year=2023,
            title="Calibration of groundwater seepage against the spatial distribution of "
            "the stream network to assess catchment-scale hydraulic properties",
            venue="Hydrology and Earth System Sciences",
            doi="10.5194/hess-27-3221-2023",
        ),
        Reference(
            key="abherve2024headwater",
            authors="Abherve, R., Roques, C., de Dreuzy, J.-R., Datry, T., Brunner, P., "
            "Longuevergne, L., Aquilina, L.",
            year=2024,
            title="Improving calibration of groundwater flow models using headwater "
            "streamflow intermittence",
            venue="Hydrological Processes",
            doi="10.1002/hyp.15167",
        ),
        Reference(
            key="abherve2025climate",
            authors="Abherve, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L., "
            "Chatton, E., Brunner, P., Aquilina, L., Serviere, L.",
            year=2025,
            title="Projected climate change impacts on groundwater-surface water "
            "connectivity in a compartmentalized mountain headwater bedrock aquifer",
            venue="Water Resources Research",
            doi="10.1029/2025WR040083",
        ),
    )

    support: Mapping[str, str] = {
        # A case in this repository runs the two stages on MODFLOW 6, DIS and DISV.
        "modflow6": "tested",
        # Nothing structural forbids it: NWT serves a head at a cell and a per-cell
        # release flux, which is all stage one reads. Nobody has run it.
        "modflow_nwt": "expected_untested",
        # Boussinesq computes a saturation excess per cell and its mesh carries the
        # connectivity, the areas and the elevations, so the criterion is reachable.
        # Nobody has run the two stages end to end.
        "boussinesq": "expected_untested",
    }

    deviations = (
        Deviation(
            key="tau_specific_ratio",
            paper="zero: a cell is a seepage face on the purely geometric test",
            here="1e-4 of the cell's own recharge by default; 0 reproduces the paper",
            why=(
                "a strictly geometric test counts a cell releasing a negligible "
                "trickle, which on a fine mesh inflates the simulated network; the "
                "paper's own value reproduces the publication exactly."
            ),
            paper_value=0.0,
        ),
        Deviation(
            key="observed_position_accuracy",
            paper="the validity length is the DEM resolution and nothing else",
            here="unset, so the paper's reading holds unless a file states it; declared, "
            "it raises the cell size h of the automatic validity length to "
            "max(h_obs, accuracy), and never changes roptim",
            why=(
                "the positional accuracy of the mapped network does not improve "
                "because the mesh is refined, so without a floor the validity length "
                "follows the mesh; declaring it is a departure and is left to the file."
            ),
            paper_value=None,
        ),
        Deviation(
            key="validity_length",
            paper="Eq. 4, roptim = Doptim / DEMres <= 2: two pixels of the DEM, one of "
            "them budgeted for the error of the mapped network (HESS p. 3224)",
            here="'auto', a length in metres: 2 h, h being h_obs, the cell size on the "
            "mapped network (the DEM pixel on a regular grid, so the paper's bound "
            "there), raised to observed_position_accuracy when declared. With "
            "[geographic.snap_streams] in 'diagnose' or 'apply' it is h + max(h, F), F "
            "the floor the snap measured. A declared length replaces it. roptim is "
            "still published as Doptim / h_obs, the paper's Eq. 3",
            why=(
                "Doptim barely falls as the mesh is refined while two cells do, so a "
                "bound in cells declares an exact model invalid on a fine mesh for a "
                "map-to-DEM mismatch the paper itself names as the limit (HESS "
                "p. 3227). Reading the paper's two pixels as one for the hydrogeology "
                "and one for the map, and replacing the latter by F when F is larger, "
                "is an interpretation: the paper never writes 2 = 1 + 1."
            ),
            paper_value="auto",
        ),
        Deviation(
            key="diagonal_neighbors",
            paper="the descent follows a D8 flowpath, which is what "
            "wbt.downslope_distance_to_stream traces",
            here="true by default, matching the paper; false departs to a D4 descent "
            "over shared edges only",
            why=(
                "a D4 descent cannot follow a talweg that runs diagonally across a "
                "square grid, and the delineation that produces the catchment uses a D8 "
                "pointer, so a criterion left at D4 would not descend the basin the way "
                "its own catchment was cut. Measured on a synthetic diagonal valley, the "
                "most accumulated cell collects 6.6 per cent of the domain under shared "
                "edges and 100 per cent under shared nodes; measured on Nancon, the cell "
                "at the basin outlet drains 0.107 of 64.631 km2 under shared edges. "
                "Setting it false returns to that D4 approximation and every result "
                "obtained under the old default."
            ),
            paper_value=True,
        ),
        Deviation(
            key="weighting",
            paper="one cell one vote",
            here="'cell' by default, the paper's value; 'area' is offered and departs",
            why=(
                "'area' exists because a mesh refined along the streams has its highest "
                "cell density exactly where distances are smallest, so one vote per cell "
                "over-weights the refined reaches. Choosing it leaves the publication."
            ),
            paper_value="cell",
        ),
        Deviation(
            key="outlet_sealed_into_d_so_target",
            paper="not addressed: the outlet is not treated specially in D_so's target",
            here="the catchment's own outlet cell is sealed into the target of D_so, "
            "beside the mapped network and any water body",
            why=(
                "the scored catchment is every cell whose descent reaches the outlet, "
                "so every simulated flowpath in it ends there by construction, and "
                "without sealing it in, the outlet cell would count as unmatched "
                "seepage for the sole reason that it is the basin's exit, not because "
                "the network disagrees with the map."
            ),
        ),
        Deviation(
            key="max_unreachable_fraction",
            paper="not addressed: the authors' own code drops an unreached cell "
            "silently before averaging (objective_function.py)",
            here="an unreached distance is capped at L_cap (the longest descent to "
            "the outlet, not dropped) rather than left out of the mean, and the run "
            "is refused when more than 5 per cent of D_so's support never reaches "
            "the mapped network",
            why=(
                "silently dropping unreached cells lets an ill-conditioned run report "
                "a favourable D_so from a support that has quietly shrunk; capping "
                "counts every cell as a large but finite penalty instead, and the "
                "5 per cent guard catches the case where too much of the support is "
                "gone for the average to mean anything."
            ),
        ),
        Deviation(
            key="bisection_variable_and_sweep",
            paper="a dichotomy, its variable and scale not stated in the text; the "
            "authors' own code bisects linearly in K/R over [1, 10000]",
            here="bisection in log10 K, preceded by a 7-point log-spaced sweep of the "
            "bounds to locate a sign change before bisecting",
            why=(
                "K/R spans decades on a real catchment, so a linear midpoint search "
                "spends almost every step on the wrong end of the interval; the sweep "
                "exists because a plain midpoint search is not guaranteed to bracket a "
                "sign change on its own, and the criterion is refused rather than run "
                "past a bracket that never finds one."
            ),
        ),
        Deviation(
            key="d_os_support",
            paper="the printed text (HESS p. 3225) leaves D_os's support as each "
            "pixel of the observed streams, unmodified; the authors' own published "
            "code (Zenodo, objective_function.py:157-164) instead traces every "
            "mapped pixel downslope with the same D8 flow-tracing it uses for the "
            "simulated network, closing the observed network exactly as it closes "
            "the simulated one",
            here="raw mapped-network pixels, never closed downslope: this follows "
            "the printed text, not the authors' code",
            why=(
                "closing the observed network the way the code does would build the "
                "observation out of the DEM's own descent, which erases the very "
                "signal Eq. 4 exists to detect: a misregistered or truncated mapped "
                "network would then read as well matched simply because the "
                "topography closes the gap for it. Tested on a synthetic V-valley "
                "(tests/unit/core/test_v_valley_support_bench.py), where closing the "
                "observed target instead moves roptim's root by more than a factor "
                "of ten."
            ),
        ),
        Deviation(
            key="dem_correc_type",
            paper="FillDepressions on the DEM, which then serves both the catchment "
            "delineation and the distances",
            here="'fill' by default, the paper's tool, for the raster delineation, "
            "which builds the model domain and places the outlet; 'breach' is "
            "offered and departs. Either way the criterion fills the model top on "
            "the mesh graph by a priority flood seeded on the domain border, and "
            "reads its catchment there, upstream of the outlet",
            why=(
                "'breach' exists because it moves far fewer cells than filling, which "
                "a delineation on a fine DEM with road embankments can need. The "
                "criterion does not descend that raster: sampled on another mesh it "
                "grows new pits, so the top is filled on the graph the distances use, "
                "the paper's fill. A breached raster reaches the criterion only "
                "through the outlet and the domain, and the gap between the raster "
                "polygon and the scored catchment is published per trial as "
                "catchment_mismatch. Choosing it leaves the publication."
            ),
            paper_value="fill",
        ),
        Deviation(
            key="observed_rasterization",
            paper="the mapped network is rasterised onto the model grid by "
            "WhiteboxTools' VectorLinesToRaster, whose own assignment rule is not "
            "restated in the text",
            here="'crossing' by default, matching the paper: a cell belongs to the "
            "network when the line crosses the segment joining two edge-sharing "
            "cell centres, WhiteboxTools' own rule on a structured grid, except "
            "that a reach crossing no such segment keeps the cell holding its "
            "midpoint where WhiteboxTools drops it (counted per trial as "
            "n_observed_features_fallback); 'touch' is offered and departs, keeping "
            "every cell the line geometry intersects, corners included",
            why=(
                "crossing draws the map one cell wide, like the simulated network, so "
                "a model that matches the map scores J = 0; touch grows D_os on every "
                "diagonal step of the map and pulls the search off that zero even on a "
                "perfect match. 'touch' is kept to replay a session recorded before "
                "2026-09. Choosing it leaves the publication. The midpoint fallback "
                "keeps every mapped reach on the mesh, so none disappears silently."
            ),
            paper_value="crossing",
        ),
        Deviation(
            key="spin_up_year",
            paper="stage two simulates 2020 to 2023 and scores June to October of the "
            "drought year 2022 alone (WRR 2025, Fig. 5): the years before are simulated "
            "and not scored",
            here="with no scoring_window on the protocol or on [calibration], and no "
            "warmup_periods, stage two leaves the first year of [simulation.time] out: "
            "it scores from one year after start_datetime to the end of the run, every "
            "block it scores alike. A declared window replaces it. A run of one year "
            "or less has nothing past its spin-up and is scored whole",
            why=(
                "the first year starts from an initial condition the run did not "
                "produce and still carries it; scored, it fits the storage to that "
                "initial condition as much as to the aquifer. "
                "The paper's low-flow months of one year are a choice for its site and "
                "its question, which no default can carry, so the default keeps the "
                "whole record past the spin-up and leaves that window to the file."
            ),
        ),
    )

    adjustable = frozenset(
        {
            "conductivity",
            "storage",
            "network_output",
            "steady_metric",
            "steady_method",
            "steady_max_iter",
            "steady_tolerance",
            "steady_method_options",
            "steady_window",
            "transient_metric",
            "transient_method",
            "transient_max_iter",
            "transient_tolerance",
            "transient_method_options",
            "discharge_variable",
            "observed_station_id",
            "scoring_window",
        }
    )
    """Everything the options model exposes. Changing one keeps the method; the
    record still says which values were used, because a reader comparing to the
    publication needs to know that the engine was swapped."""

    def expand(self, options: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
        """Return the document with the two stages and their objective block written.

        The transient stage scores itself through a block that reads a point
        output observing the gauging station, except when that station is not
        known from the document alone (several loaded, or a source that
        discovers its stations at load time): then it keeps writing
        ``variable`` + ``objective``, the single-metric route, which resolves
        the station once the records are loaded, exactly as before this stage
        could name a block at all.
        """
        opts = MatchingHydrographicNetworkOptions.model_validate(
            {"name": self.name, **dict(options)}
        )
        if opts.version is not None and str(opts.version) != self.version:
            raise ValueError(
                f"[calibration.protocol] pins {self.name!r} at version "
                f"{opts.version!r}, and this installation carries {self.version!r}. A "
                "pin exists so a result stays replayable, so it is refused rather than "
                "approximated."
            )
        expanded = copy.deepcopy(dict(document))
        calibration = dict(expanded.get("calibration") or {})

        parameters = calibration.get("parameters") or {}
        _require_parameter(parameters, opts.conductivity, "conductivity", opts.storage)
        if opts.storage is not None:
            _require_parameter(parameters, opts.storage, "storage", opts.storage)

        outputs = dict(calibration.get("outputs") or {})
        network_output = _resolve_network_output(outputs, opts)

        objective_blocks = [
            {
                "name": NETWORK_BLOCK,
                "metric": opts.steady_metric,
                "uses_outputs": [network_output],
            }
        ]
        station = _resolve_observed_station(document, opts) if opts.storage is not None else None
        if station is not None:
            _write_hydrograph_output(outputs, opts, station)
            objective_blocks.append(
                {
                    "name": HYDROGRAPH_BLOCK,
                    "metric": opts.transient_metric,
                    "uses_outputs": [HYDROGRAPH_OUTPUT],
                }
            )
        calibration["outputs"] = outputs
        calibration["objective_blocks"] = objective_blocks
        scored_from = _first_date_past_the_spin_up(document, opts) if opts.storage else None
        calibration["phases"] = _phases(
            opts, scores_a_known_station=station is not None, scored_from=scored_from
        )
        expanded["calibration"] = calibration
        return expanded


def _require_parameter(
    parameters: Mapping[str, Any], name: str, role: str, storage: str | None
) -> None:
    if name in parameters:
        return
    declared = ", ".join(sorted(parameters)) or "nothing"
    hint = f"'{role}' in [calibration.protocol]"
    raise ValueError(
        f"protocol 'matching_hydrographic_network' moves {name!r} as its {role}, but "
        f"[calibration.parameters] declares {declared}. Declare it, or point {hint} at "
        "the name this file uses."
    )


def _resolve_network_output(
    outputs: Mapping[str, Any], opts: MatchingHydrographicNetworkOptions
) -> str:
    if opts.network_output is not None:
        if opts.network_output not in outputs:
            declared = ", ".join(sorted(outputs)) or "nothing"
            raise ValueError(
                f"[calibration.protocol].network_output names {opts.network_output!r}, "
                f"but [calibration.outputs] declares {declared}."
            )
        return opts.network_output

    candidates = [
        name
        for name, decl in outputs.items()
        if isinstance(decl, Mapping) and decl.get("support") == "network"
    ]
    if not candidates:
        raise ValueError(
            "protocol 'matching_hydrographic_network' is scored on a network output, and "
            '[calibration.outputs] declares none. Add one with support = "network" and '
            "the path to the mapped stream network."
        )
    if len(candidates) > 1:
        joined = ", ".join(sorted(candidates))
        raise ValueError(
            f"[calibration.outputs] declares several network outputs ({joined}); name the "
            "one the protocol is scored on in [calibration.protocol].network_output."
        )
    return candidates[0]


def _resolve_observed_station(
    document: Mapping[str, Any], opts: MatchingHydrographicNetworkOptions
) -> str | None:
    """Return the one gauging station to observe, or ``None`` when it is not known here.

    Named explicitly, ``observed_station_id`` always answers. Otherwise the
    station is read statically, from the file's own
    ``[[data.hydrometry.sources]]``: the protocol writes the output before any
    data is loaded, unlike ``discharge_target``, which resolves the same
    question at run time from what actually got loaded.

    ``None`` is returned, not raised, for exactly what ``discharge_target``
    itself has to resolve at run time: a source that discovers its stations
    at load time (an ``extent`` or a ``mask_path``, no ``station_ids``), or
    several named across the sources. Guessing wrong here would write a block
    fitted to the wrong gauge and never say so; the caller falls back to the
    single-metric route instead, which keeps resolving it as it always has.
    """
    if opts.observed_station_id is not None:
        return opts.observed_station_id

    data = document.get("data")
    hydrometry = data.get("hydrometry") if isinstance(data, Mapping) else None
    sources = hydrometry.get("sources") if isinstance(hydrometry, Mapping) else None
    if not isinstance(sources, list) or not sources:
        return None

    candidates: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            return None
        station_ids = source.get("station_ids")
        if not station_ids:
            return None
        for station_id in station_ids:
            candidates.add(str(station_id))

    return next(iter(candidates)) if len(candidates) == 1 else None


def _write_hydrograph_output(
    outputs: dict[str, Any], opts: MatchingHydrographicNetworkOptions, station: str
) -> None:
    """Write, or check, the point output the transient stage's block reads.

    The output's location is the station's own record, not a coordinate: a
    'point' output needs neither 'x'/'y' nor 'geometry' once it 'observes' one.
    A file that already names ``HYDROGRAPH_OUTPUT`` for something else is
    refused rather than silently overwritten, the same way a name collision on
    a parameter is. Compared through the output model
    (:func:`hydromodpy.calibration.config.outputs_agree`), not raw: a sealed
    run's own dump spells out every default this bare declaration leaves out,
    and reloading it must not read as a collision with itself.
    """
    written = {
        "variable": opts.discharge_variable,
        "support": "point",
        "observes": station,
    }
    existing = outputs.get(HYDROGRAPH_OUTPUT)
    if existing is not None and not outputs_agree(existing, written):
        raise ValueError(
            f"[calibration.outputs].{HYDROGRAPH_OUTPUT!r} is reserved for the point "
            "output the transient stage of protocol 'matching_hydrographic_network' "
            "writes, and this file declares something else there. Rename it."
        )
    outputs[HYDROGRAPH_OUTPUT] = written


def _first_date_past_the_spin_up(
    document: Mapping[str, Any], opts: MatchingHydrographicNetworkOptions
) -> str | None:
    """Return the first date the transient stage scores by default, or ``None``.

    The transient stage runs the project's own time grid, whose first year
    starts from an initial condition the run did not produce. Left unwindowed,
    the hydrograph and any network block scored in that phase would read it,
    and a two-bound network would count it as one more complete year. So the
    default window opens one year after ``[simulation.time].start_datetime``.

    ``None`` when a declaration already says what the phase scores, and wins:
    ``scoring_window`` on the protocol, ``scoring_window`` or
    ``warmup_periods`` on ``[calibration]``. ``None`` too for a document
    already carrying a transient stage without a window: a run sealed before
    this default replays the window it ran with. And ``None`` when no start
    date is written, where the stage cannot run transient anyway.

    A run that ends within its first year, or on its first anniversary, gets
    no window either: nothing lies past the spin-up to score, and refusing
    the file here would also refuse the steady stage, which reads the same
    record and needs no spin-up.
    """
    if opts.scoring_window is not None:
        return None
    calibration = document.get("calibration")
    calibration = calibration if isinstance(calibration, Mapping) else {}
    if calibration.get("scoring_window") is not None or calibration.get("warmup_periods"):
        return None
    for phase in calibration.get("phases") or ():
        if isinstance(phase, Mapping) and phase.get("name") == TRANSIENT_STAGE:
            if phase.get("scoring_window") is None:
                return None
            break

    simulation = document.get("simulation")
    time = simulation.get("time") if isinstance(simulation, Mapping) else None
    time = time if isinstance(time, Mapping) else {}
    return _date_past_the_spin_up(time.get("start_datetime"), time.get("end_datetime"))


def _date_past_the_spin_up(start: Any, end: Any) -> str | None:
    """Return the first date scored once a one-year spin-up is left out.

    ``start`` and ``end`` are ``[simulation.time]``'s bounds, as a date, a
    datetime or a string. ``None`` when ``start`` is unset, or when the run
    ends within its first year or on its first anniversary: nothing lies past
    the spin-up to score, so the stage scores the whole run, and
    :func:`why_the_spin_up_year_is_scored` says so.
    """
    first = _instant(start, "[simulation.time].start_datetime")
    if first is None:
        return None
    first_scored = first + pd.DateOffset(years=1)
    last = _instant(end, "[simulation.time].end_datetime")
    if (
        last is not None
        and (last.tzinfo is None) == (first_scored.tzinfo is None)
        and first_scored >= last
    ):
        return None
    return _spelled(first_scored)


def why_the_spin_up_year_is_scored(calibration: Any, time: Any) -> str | None:
    """Return why the default spin-up window did not reach the transient stage.

    ``calibration`` is the validated ``[calibration]`` section, expanded;
    ``time`` is ``[simulation.time]``. ``None`` when the window reached the
    stage, when a window or a warm-up the file declares replaces it, when the
    protocol writes no transient stage, or when no start date is written.
    The expansion drops the window without a word, so ``hmp calibrate
    --check`` prints what this returns.
    """
    declared = getattr(calibration, "protocol", None)
    if getattr(declared, "name", None) != MatchingHydrographicNetwork.name:
        return None
    if declared.storage is None or declared.scoring_window is not None:
        return None
    if calibration.scoring_window is not None or calibration.warmup_periods:
        return None
    phase = next((p for p in calibration.phases or () if p.name == TRANSIENT_STAGE), None)
    if phase is None or phase.scoring_window is not None:
        return None
    start = getattr(time, "start_datetime", None)
    if start is None:
        return None
    end = getattr(time, "end_datetime", None)
    if _date_past_the_spin_up(start, end) is None:
        return (
            f"[simulation.time] ends on {pd.Timestamp(end):%Y-%m-%d}, within one year of "
            f"its start {pd.Timestamp(start):%Y-%m-%d}, so nothing lies past the spin-up "
            "to score. Lengthen the run, or write [calibration.protocol].scoring_window "
            "to say what it scores."
        )
    return (
        f"the {TRANSIENT_STAGE} phase this file writes has no scoring_window, so the "
        "default window, one year after start_datetime, does not apply."
    )


def _instant(value: Any, source: str) -> pd.Timestamp | None:
    """Return a TOML date, datetime or string as a timestamp, ``None`` when unset."""
    if value is None or value == "":
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} is not a date: {value!r}.") from exc
    if stamp is pd.NaT:
        raise ValueError(f"{source} is not a date: {value!r}.")
    return stamp


def _spelled(stamp: pd.Timestamp) -> str:
    """Return one spelling of an instant: its date at midnight, ISO 8601 otherwise.

    A TOML file writes the same start three ways, and the stage written from
    it must not depend on which: a run re-read from its own dump has to expand
    to the stages it ran.
    """
    if stamp.tzinfo is None and stamp == stamp.normalize():
        return stamp.strftime("%Y-%m-%d")
    return stamp.isoformat()


def _phases(
    opts: MatchingHydrographicNetworkOptions,
    *,
    scores_a_known_station: bool,
    scored_from: str | None = None,
) -> list[dict[str, Any]]:
    # The regime says steady and runners/phase_regime.py writes what it means:
    # one period over the window, read from [simulation.time] unless the file
    # names one. So the stages written here never depend on how a date is spelled.
    over = "its steady_window" if opts.steady_window is not None else "the record"
    steady: dict[str, Any] = {
        "name": STEADY_STAGE,
        "description": (
            "Match the simulated seepage network to the mapped one by moving "
            f"{opts.conductivity}, steady state over {over}."
        ),
        "method": opts.steady_method,
        "max_iter": opts.steady_max_iter,
        "parameters": [opts.conductivity],
        "objective_blocks": [NETWORK_BLOCK],
        "freeze_on_success": True,
        "regime": "steady",
    }
    if opts.steady_window is not None:
        steady["steady_window"] = dict(opts.steady_window)
    if opts.steady_tolerance is not None:
        steady["tolerance"] = float(opts.steady_tolerance)
    if opts.steady_method_options:
        steady["method_options"] = dict(opts.steady_method_options)
    if opts.storage is None:
        return [steady]

    # The window bounds every block the phase scores, a network one included,
    # so the spin-up year leaves the hydrograph and a two-bound extent alike.
    spin_up = (
        f", scored from {scored_from} on, the first year of the run left out as spin-up"
        if opts.scoring_window is None and scored_from is not None
        else ""
    )
    transient: dict[str, Any] = {
        "name": TRANSIENT_STAGE,
        "description": (
            f"Read {opts.storage} from the observed hydrograph, "
            f"{opts.conductivity} frozen, transient{spin_up}."
        ),
        "method": opts.transient_method,
        "max_iter": opts.transient_max_iter,
        "parameters": [opts.storage],
        "depends_on": STEADY_STAGE,
        "regime": "transient",
    }
    if scores_a_known_station:
        transient["objective_blocks"] = [HYDROGRAPH_BLOCK]
    else:
        # observed_station_id is unset here: a set one always resolves a
        # station (see _resolve_observed_station), so this route is only
        # reached with several stations loaded, or a source that discovers
        # its own at load time; discharge_target refuses the former by name.
        transient["variable"] = opts.discharge_variable
        transient["objective"] = opts.transient_metric
    if opts.transient_tolerance is not None:
        transient["tolerance"] = float(opts.transient_tolerance)
    if opts.transient_method_options:
        transient["method_options"] = dict(opts.transient_method_options)
    if opts.scoring_window is not None:
        transient["scoring_window"] = dict(opts.scoring_window)
    elif scored_from is not None:
        transient["scoring_window"] = {"start": scored_from}
    return [steady, transient]


def options_the_recipe_already_runs(
    opts: MatchingHydrographicNetworkOptions, calibration: Any, time: Any
) -> frozenset[str]:
    """Return the options a file wrote to the value the recipe runs anyway.

    The recipe leaves a stage's method options and its precision to the method,
    and the spin-up window to the run's first year. A file that writes the same
    thing out, ``sweep_points = 7`` beside a bisection whose default is seven,
    has not moved off the recipe, and ``hmp calibrate --check`` must not say it
    has. ``calibration`` is the validated ``[calibration]`` section and ``time``
    ``[simulation.time]``.
    """
    same = set(opts.stage_options_run_as_their_method_does())
    if opts.scoring_window is not None and _is_the_spin_up_window(
        opts.scoring_window, calibration, time
    ):
        same.add("scoring_window")
    return frozenset(same)


def _is_the_spin_up_window(window: Mapping[str, Any], calibration: Any, time: Any) -> bool:
    """Say whether a declared window scores what the default spin-up window scores.

    That default opens one year after the run starts and runs to its end. It is
    only the recipe's when nothing on ``[calibration]`` bounds the scoring.
    """
    if getattr(calibration, "scoring_window", None) is not None:
        return False
    if getattr(calibration, "warmup_periods", None):
        return False
    start = getattr(time, "start_datetime", None)
    end = getattr(time, "end_datetime", None)
    first_scored = _date_past_the_spin_up(start, end)
    if first_scored is None or window.get("start") is None:
        return False
    if pd.Timestamp(window["start"]) != pd.Timestamp(first_scored):
        return False
    written_end = window.get("end")
    if written_end is None:
        return True
    return end is not None and pd.Timestamp(written_end) >= pd.Timestamp(end)


__all__ = [
    "HYDROGRAPH_BLOCK",
    "HYDROGRAPH_OUTPUT",
    "NETWORK_BLOCK",
    "STEADY_STAGE",
    "TRANSIENT_STAGE",
    "MatchingHydrographicNetwork",
    "options_the_recipe_already_runs",
    "why_the_spin_up_year_is_scored",
]
