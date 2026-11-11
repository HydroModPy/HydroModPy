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
from pydantic import ValidationError

from hydromodpy.calibration.config import window_of_the_run
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_outputs import outputs_agree
from hydromodpy.calibration.protocols.base import Deviation, Reference
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

STEADY_STAGE = "steady_conductivity"
TRANSIENT_STAGE = "transient_storage"
NETWORK_BLOCK = "network_extension"
HYDROGRAPH_OUTPUT = "hydrograph"
HYDROGRAPH_BLOCK = "hydrograph"

_DEFAULTS_1_2: Mapping[str, Any] = {
    "model": {"seepage_threshold": 1.0e-4, "weighting": "cell", "neighbours": "D8"},
    "map": {
        "drawn_by": "crossing",
        "clip_to_catchment": False,
        "heads": {"radius": 100.0, "min_drained_area": 0.02},
    },
    "verdict": {"validity_length": "auto", "max_catchment_mismatch": False},
}

DEFAULTS_BY_VERSION: Mapping[str, Mapping[str, Any]] = {
    "1.2": _DEFAULTS_1_2,
    "1.3": {
        "model": _DEFAULTS_1_2["model"],
        "map": {**_DEFAULTS_1_2["map"], "drawn_by": "heads", "clip_to_catchment": True},
        "verdict": {**_DEFAULTS_1_2["verdict"], "max_catchment_mismatch": 0.05},
    },
}
"""What each version of the protocol writes in the network output, one line per version.

A key the file leaves empty takes the value of the version the file runs, so
moving a default in :mod:`hydromodpy.core.scoring.stream_defaults` cannot move
a pinned file. The keys are the ones that change a number, or refuse a search:
the three that only decide what is logged stay with the model. The last line is
what a file without a pin runs. A test holds it equal to the defaults of the
model, so a default that moves without a new line here fails.

1.2 is the method as it ran on 2026-09-28: the mapped network drawn by the
crossing rule, read whole from a file, with no veto. 1.3 draws it from its heads,
cuts it to the catchment and refuses a catchment that is not the delineated one.
"""


class MatchingHydrographicNetwork:
    """Conductivity from the mapped stream network, storage from the hydrograph."""

    name = "matching_hydrographic_network"
    defaults_by_version = DEFAULTS_BY_VERSION
    version = next(reversed(DEFAULTS_BY_VERSION))
    """The last line of :data:`DEFAULTS_BY_VERSION`, what a file without a pin runs.

    Bumped from 1.2 to 1.3: the map is drawn from its heads, cut to the catchment
    with no cut end taken for a head, and a scored catchment too far from the
    delineated one is refused before the first solve. A pin on 1.2 keeps the
    crossing rule, the whole file and no refusal.

    Bumped from 1.1 to 1.2, 1.1 being what v2.0.0a1 released: the DEM is filled
    rather than breached before the catchment is cut ([geographic].dem_correc_type),
    the transient stage leaves the first year of the run out as spin-up, and the
    bound of Eq. 4 is a length in meters (verdict.validity_length = 'auto') where it was
    roptim_max = 2 on a ratio to the cell size.

    Bumped from 1.0 to 1.1: the descent used to build the criterion defaulted
    to D8, and the validity bound of Eq. 4 was read only at the point the
    search returns rather than at every trial.

    A pin on a version outside the table is refused rather than approximated.
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
        "against the observed hydrograph, scored on the scoring window the file declares, "
        "else on [metrics] window, else after the first year of the run, the spin-up.",
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

    declared_observables = ("release_flux", "discharge")
    """What the stages of this method read.

    Stage one scores a trial on the release flux of the cells it calls seepage
    faces, stage two on the discharge of the outlet, and this declaration says
    both instead of a verdict per backend.
    """

    deviations = (
        Deviation(
            key="model.seepage_threshold",
            paper="zero: a cell is a seepage face on the purely geometric test",
            here="1e-4 of the mean basin recharge by default; 0 reproduces the paper",
            why=(
                "a strictly geometric test counts a cell releasing a negligible "
                "trickle, which on a fine mesh inflates the simulated network; the "
                "paper's own value reproduces the publication exactly."
            ),
            paper_value=0.0,
        ),
        Deviation(
            key="map.position_accuracy",
            paper="the validity length is the DEM resolution and nothing else",
            here="unset, so the paper's reading holds unless a file states it; declared, "
            "it raises the cell size h of the automatic validity length to "
            "max(h_obs, accuracy), and never changes r_optim",
            why=(
                "the positional accuracy of the mapped network does not improve "
                "because the mesh is refined, so without a floor the validity length "
                "follows the mesh; declaring it is a departure and is left to the file."
            ),
            paper_value=None,
        ),
        Deviation(
            key="verdict.validity_length",
            paper="Eq. 4, r_optim = D_optim / DEMres <= 2: two pixels of the DEM, one of "
            "them budgeted for the error of the mapped network (HESS p. 3224)",
            here="'auto', a length in metres: 2 h, h being h_obs, the cell size on the "
            "mapped network (the DEM pixel on a regular grid, so the paper's bound "
            "there), raised to map.position_accuracy when declared. A declared "
            "length replaces it. r_optim is still published as D_optim / h_obs, the "
            "paper's Eq. 3",
            why=(
                "D_optim barely falls as the mesh is refined while two cells do, so a "
                "bound in cells declares an exact model invalid on a fine mesh for a "
                "map-to-DEM mismatch the paper itself names as the limit (HESS "
                "p. 3227)."
            ),
            paper_value="auto",
        ),
        Deviation(
            key="model.neighbours",
            paper="the descent follows a D8 flowpath, which is what "
            "wbt.downslope_distance_to_stream traces",
            here="'D8' by default, matching the paper; 'D4' departs to a descent "
            "over shared edges only",
            why=(
                "a D4 descent cannot follow a talweg that runs diagonally across a "
                "square grid, and the delineation that produces the catchment uses a D8 "
                "pointer, so a criterion left at D4 would not descend the basin the way "
                "its own catchment was cut. Measured on a synthetic diagonal valley, the "
                "most accumulated cell collects 6.6 per cent of the domain under shared "
                "edges and 100 per cent under shared nodes; measured on Nancon, the cell "
                "at the basin outlet drains 0.107 of 64.631 km2 under shared edges. "
                "Setting it to 'D4' returns to that approximation and every result "
                "obtained under the old default."
            ),
            paper_value="D8",
        ),
        Deviation(
            key="model.weighting",
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
            always=True,
        ),
        Deviation(
            key="unreached_distance_capped",
            paper="not addressed: the authors' own code drops an unreached cell "
            "silently before averaging (objective_function.py)",
            here="an unreached distance is capped at L_cap, the longest descent to the "
            "outlet, and stays in the mean",
            why=(
                "silently dropping unreached cells lets a run report a favourable "
                "distance from a support that has quietly shrunk; capping counts "
                "every cell as a large but finite penalty instead. With the outlet "
                "sealed the cap only ever reaches D_os: every cell of the scored "
                "catchment reaches the target of D_so."
            ),
            always=True,
        ),
        Deviation(
            key="verdict.max_catchment_mismatch",
            paper="no bound: the paper scores the pixels of the delineated catchment, so "
            "the question does not arise on its raster",
            here="the search is refused before its first solve when the catchment read on "
            "the descent graph differs from the delineated outline by more than the bound "
            "of verdict.max_catchment_mismatch, as a share of its area: 5 per cent from "
            "version 1.3, no bound on 1.2",
            why=(
                "the criterion scores the cells whose descent reaches the outlet on the "
                "mesh graph, and those may not be the catchment asked for. On Nancon the "
                "gap is 0.4 per cent on the default grid and 1.5 to 2.4 on Voronoi meshes "
                "of 200 and 100 m; it passes 5 per cent on coarse grids (11 per cent on 30 by 30 "
                "cells, 3.8 per cent on 60 by 60, 5.6 per cent on 120 by 120), where the outlet "
                "closes on another branch, and where the two conditionings of one DEM, the one "
                "that cuts the polygon and the one the descent graph is built on, disagree "
                "along the divide, which no mesh refinement closes."
            ),
            paper_value=False,
        ),
        Deviation(
            key="steady_recharge_window",
            paper="the recharge of the steady stage is the mean of 1960 to 2019 (HESS 2023, "
            'p. 3224), a sixty-year normal, and WRR 2025 applies "the mean rescaled recharge '
            'from the historical reanalysis (2020-2023)", the mean of the record it loads',
            here="the mean of the window the run loads, [simulation.time] or steady_window, "
            "printed beside K with its dates; it is the publication's own reading once "
            "steady_window is written to a window the forcing covers",
            why=(
                "K/R is what the stage identifies, so K follows the R a file can load. A "
                "protocol cannot invent a normal the forcing does not cover. Write a long "
                "steady_window when it does cover one, and read R beside K before citing K."
            ),
            holds=lambda calibration, metrics_window: (
                getattr(getattr(calibration, "protocol", None), "steady_window", None) is None
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
            always=True,
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
                "(tests/unit/catchment/drainage/test_distance.py), where closing the "
                "observed target instead moves r_optim's root by more than a factor "
                "of ten."
            ),
            always=True,
        ),
        Deviation(
            key="dem_correc_type",
            paper="FillDepressions on the DEM, which then serves both the catchment "
            "delineation and the distances",
            here="'fill' by default, the paper's tool, for the raster delineation, "
            "which builds the model domain and places the outlet; 'breach' is "
            "offered and departs, as is 'capped_breach', which breaches only "
            "within a cumulative depth and a length in metres ([geographic.capped_breach]) "
            "and fills the depressions those limits refused. Either way the "
            "criterion fills the model top on the mesh graph by a priority flood "
            "seeded on the domain border, and reads its catchment there, upstream "
            "of the outlet",
            why=(
                "'breach' exists because it moves far fewer cells than filling, which "
                "a delineation on a fine DEM with road embankments can need, and "
                "'capped_breach' because an unbounded breach can dig deep: it bounds "
                "the cumulative lowering of a breach path and its length, and fills "
                "the rest. The "
                "criterion does not descend that raster: sampled on another mesh it "
                "grows new pits, so the top is filled on the graph the distances use, "
                "the paper's fill. A breached raster reaches the criterion only "
                "through the outlet and the domain, and the gap between the raster "
                "polygon and the scored catchment is published per trial as "
                "catchment_mismatch. Choosing either leaves the publication."
            ),
            paper_value="fill",
        ),
        Deviation(
            key="map.drawn_by",
            paper="the mapped network is rasterised onto the model grid by "
            "WhiteboxTools' VectorLinesToRaster, whose own assignment rule is not "
            "restated in the text",
            here="'heads' from version 1.3 (1.2 draws 'crossing'), and it departs from the "
            "paper: it keeps the free "
            "ends of the map and traces the model's own descent from each, so the "
            "map is connected to the outlet by construction and the path a field "
            "or a ditch gave the mapped line no longer counts as error; an end the "
            "cut to the catchment made is no head; 'crossing' "
            "is offered and matches the paper, a cell belongs to the network when "
            "the line crosses the segment joining two edge-sharing cell centres, "
            "WhiteboxTools' own rule on a structured grid, except that a reach "
            "crossing no such segment keeps the cell holding its midpoint where "
            "WhiteboxTools drops it (counted per trial as n_observed_features_"
            "fallback); 'touch' is offered and departs, keeping every cell the "
            "line geometry intersects, corners included",
            why=(
                "the mapped path below a stream head is shaped by fields, ditches "
                "and rectified reaches that a model built on a DEM can never "
                "reproduce, which crossing and touch both score as error; heads "
                "lets the model draw that path itself and scores only where the "
                "network starts and how far it reaches. 'crossing' stays the rule "
                "of the paper and is kept for maps that are not a tree, canals, "
                "braids and karst, where a free end is not a meaningful head. "
                "'touch' is kept to replay a session recorded before 2026-09. "
                "Choosing either leaves the publication. The midpoint fallback of "
                "crossing keeps every mapped reach on the mesh, so none disappears "
                "silently."
            ),
            paper_value="crossing",
        ),
        Deviation(
            key="map.heads.radius",
            paper="not addressed: the paper has no heads rule",
            here="under the heads rule, a mapped stream head lands on a cell within this "
            "distance of it, and a head with no such cell is lost; the value in force is "
            "printed",
            why=(
                "a mapped head is never at a cell centre, so landing it needs a distance. "
                "The radius changes which heads are drawn, so it moves K, and it is "
                "declared with its value."
            ),
            paper_value=None,
        ),
        Deviation(
            key="map.heads.min_drained_area",
            paper="not addressed: the paper has no heads rule",
            here="under the heads rule, a head lands only on a cell that drains at least this "
            "area in km2; the value in force is printed",
            why=(
                "a head next to its valley should land in the valley and not on the ridge "
                "cell beside it. The area changes which cell is drawn, so it moves K, and "
                "it is declared with its value."
            ),
            paper_value=None,
        ),
        Deviation(
            key="map.clip_to_catchment",
            paper="the text scores the mapped pixels of the catchment and says nothing of a "
            "line that leaves it",
            here="the map is cut to the delineated catchment before it is drawn, with the "
            "shape the hydrography data family clips to; false reads a file whole",
            why=(
                "a file and data.hydrography then draw the same map from the same file, and "
                "a figure redrawn from a run draws the map the trial scored. A cell of the "
                "map outside the polygon but on the scored graph leaves it: 3 cells of 499 "
                "under the crossing rule on Nancon, K unmoved to the fourth digit."
            ),
            paper_value=False,
        ),
        Deviation(
            key="spin_up_year",
            paper="stage two simulates 2020 to 2023 and scores June to October of the "
            "drought year 2022 alone (WRR 2025, Fig. 5): the years before are simulated "
            "and not scored",
            here="with no window on the protocol or on [calibration], no "
            "[metrics] window, stage two leaves the first year of "
            "[simulation.time] out: "
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
            holds=lambda calibration, metrics_window: _scores_the_spin_up_year(
                calibration, metrics_window
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
            "steady_max_trials",
            "steady_precision",
            "steady_method_options",
            "steady_window",
            "transient_metric",
            "transient_method",
            "transient_max_trials",
            "transient_precision",
            "transient_method_options",
            "discharge_variable",
            "window",
        }
    )
    """Everything the options model exposes. Changing one keeps the method; the
    record still says which values were used, because a reader comparing to the
    publication needs to know that the engine was swapped."""

    def expand(self, options: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
        """Return the document with the two stages and their objective block written.

        The network output takes the values of the version the file runs for
        each key it leaves empty (:data:`DEFAULTS_BY_VERSION`).

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
        version = self.version if opts.version is None else str(opts.version)
        if version not in DEFAULTS_BY_VERSION:
            raise ValueError(
                f"[calibration.protocol] pins {self.name!r} at version {version!r}, and this "
                f"installation carries {', '.join(DEFAULTS_BY_VERSION)}. A pin exists so a "
                "result stays replayable, so it is refused rather than approximated."
            )
        if opts.version is not None and version == "1.2":
            _tell_what_a_pin_on_1_2_runs()
        expanded = copy.deepcopy(dict(document))
        calibration = dict(expanded.get("calibration") or {})

        parameters = calibration.get("parameters") or {}
        _require_parameter(parameters, opts.conductivity, "conductivity")
        if opts.storage:
            _require_parameter(parameters, opts.storage, "storage")

        outputs = dict(calibration.get("outputs") or {})
        network_output = _resolve_network_output(outputs, opts)
        outputs[network_output] = _with_the_defaults_of(version, outputs[network_output])

        objective_blocks = [
            {
                "name": NETWORK_BLOCK,
                "metric": opts.steady_metric,
                "uses_outputs": [network_output],
            }
        ]
        station = _resolve_observed_station(document) if opts.storage else None
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
        window = _transient_window_by_default(document, opts) if opts.storage else None
        calibration["phases"] = _phases(
            opts, scores_a_known_station=station is not None, default_window=window
        )
        expanded["calibration"] = calibration
        return expanded


_TOLD: set[str] = set()


def _tell_what_a_pin_on_1_2_runs() -> None:
    """Say once that a pin on 1.2 names two methods in the history of the releases.

    The table holds 1.2 as it ran on 2026-09-28 (the crossing rule). The release
    v2.0.0a5 carried the same number with the heads rule, which a pin on 1.2 does
    not reproduce.
    """
    text = (
        "[calibration.protocol] pins version 1.2, which this release runs with "
        "map.drawn_by = 'crossing', whole map and no veto. v2.0.0a5 ran its "
        "version 1.2 under 'heads', and K differs between the two: write "
        "map.drawn_by = 'heads' in the network output to bring that back."
    )
    if text not in _TOLD:
        _TOLD.add(text)
        logger.warning(text)


def _scores_the_spin_up_year(calibration: Any, metrics_window: Any) -> bool:
    """Say whether stage two runs on the spin-up default, the first year left out.

    That default is what a file leaves when it writes no scoring window on the
    protocol or on [calibration] and no [metrics] window.
    """
    if getattr(getattr(calibration, "protocol", None), "window", None) is not None:
        return False
    if getattr(calibration, "window", None) is not None:
        return False
    return window_of_the_run(_raw_window(metrics_window)) is None


def _with_the_defaults_of(version: str, output: Any) -> Any:
    """Return a network output with the values of ``version`` for each key it leaves empty.

    A key the file writes wins, table by table at every depth. ``map.heads`` is written
    only under the heads rule, the only one that reads it. An output that is not a table
    is left to the validation of the section, which names what is wrong with it.
    """
    if not isinstance(output, Mapping):
        return output
    row = DEFAULTS_BY_VERSION[version]
    drawn = output.get("map")
    rule = row["map"]["drawn_by"]
    if isinstance(drawn, Mapping):
        rule = drawn.get("drawn_by", rule)
    if rule != "heads":
        row = {**row, "map": {key: value for key, value in row["map"].items() if key != "heads"}}
    return _under(row, output)


def _under(defaults: Mapping[str, Any], written: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``written`` over ``defaults``, a table that both hold merged key by key."""
    merged = dict(defaults)
    for key, value in written.items():
        held = merged.get(key)
        both = isinstance(held, Mapping) and isinstance(value, Mapping)
        merged[key] = _under(held, value) if both else value
    return merged


def _require_parameter(parameters: Mapping[str, Any], name: str, role: str) -> None:
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


def _resolve_observed_station(document: Mapping[str, Any]) -> str | None:
    """Return the one gauging station to observe, or ``None`` when it is not known here.

    ``[site] gauge`` answers: the gauge is the station of the catchment.
    Otherwise the station is read statically, from the file's own
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
    site = document.get("site")
    gauge = site.get("gauge") if isinstance(site, Mapping) else None
    if gauge:
        return str(gauge)

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
    (:func:`hydromodpy.calibration.config_outputs.outputs_agree`), not raw: a sealed
    run's own dump spells out every default this bare declaration leaves out,
    and reloading it must not read as a collision with itself. A declaration
    that does not validate (a sealed run's output still carrying a removed
    key) raises its own validation error, which names the key.
    """
    written = {
        "variable": opts.discharge_variable,
        "support": "point",
        "observes": station,
    }
    existing = outputs.get(HYDROGRAPH_OUTPUT)
    try:
        agree = existing is None or outputs_agree(existing, written)
    except ValidationError as exc:
        unknown = sorted(
            {str(error["loc"][-1]) for error in exc.errors() if error["type"] == "extra_forbidden"}
        )
        if not unknown:
            raise
        raise ValueError(
            f"[calibration.outputs].{HYDROGRAPH_OUTPUT!r} declares "
            f"{', '.join(repr(key) for key in unknown)}, which this output does not take: a key "
            "this version removed, or a misspelling. Delete it."
        ) from exc
    if not agree:
        raise ValueError(
            f"[calibration.outputs].{HYDROGRAPH_OUTPUT!r} is reserved for the point "
            "output the transient stage of protocol 'matching_hydrographic_network' "
            "writes, and this file declares something else there. Rename it."
        )
    outputs[HYDROGRAPH_OUTPUT] = written


def _transient_window_by_default(
    document: Mapping[str, Any], opts: MatchingHydrographicNetworkOptions
) -> dict[str, str] | None:
    """Return the window the transient stage scores by default, or ``None``.

    ``[metrics] window``, the window the run is scored on (H45), less
    ``validation_window``, when it writes both bounds. Otherwise the stage runs the project's own time grid,
    whose first year starts from an initial condition the run did not
    produce. Left unwindowed, the hydrograph would read it. So the window then
    opens one year after ``[simulation.time].start_datetime``, with no end.

    ``None`` when a declaration already says what the phase scores, and wins:
    ``window`` on the protocol or on ``[calibration]``. ``None`` too for a document
    already carrying a transient stage without a window: a run sealed before
    the spin-up default replays the window it ran with. A stage carrying the
    spin-up window keeps it, for a run sealed before ``[metrics] window``
    reached the stage. And ``None`` when no start date is written, where the
    stage cannot run transient anyway.

    A run that ends within its first year, or on its first anniversary, gets
    no spin-up window either: nothing lies past the spin-up to score, and
    refusing the file here would also refuse the steady stage, which reads the
    same record and needs no spin-up.
    """
    if opts.window is not None:
        return None
    calibration = document.get("calibration")
    calibration = calibration if isinstance(calibration, Mapping) else {}
    if calibration.get("window") is not None:
        return None
    simulation = document.get("simulation")
    time = simulation.get("time") if isinstance(simulation, Mapping) else None
    time = time if isinstance(time, Mapping) else {}
    scored_from = _date_past_the_spin_up(time.get("start_datetime"), time.get("end_datetime"))
    spin_up = {"start": scored_from} if scored_from is not None else None
    for phase in calibration.get("phases") or ():
        if isinstance(phase, Mapping) and phase.get("name") == TRANSIENT_STAGE:
            written = phase.get("window")
            if written is None:
                return None
            if spin_up is not None and _is_window(written, spin_up):
                return spin_up
            break
    metrics = document.get("metrics")
    window = window_of_the_run(
        metrics.get("window") if isinstance(metrics, Mapping) else None,
        calibration.get("validation_window"),
    )
    return window if window is not None else spin_up


def _is_window(written: Any, window: Mapping[str, str]) -> bool:
    """Say whether a raw ``window`` bounds the same instants as *window*."""
    if not isinstance(written, Mapping):
        return False
    for bound in ("start", "end"):
        here = _instant(written.get(bound), f"window.{bound}")
        there = _instant(window.get(bound), f"window.{bound}")
        if here != there:
            return False
    return True


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
    The expansion drops the window without a word, so ``hmp check``
    prints what this returns.
    """
    declared = getattr(calibration, "protocol", None)
    if getattr(declared, "name", None) != MatchingHydrographicNetwork.name:
        return None
    if not declared.storage or declared.window is not None:
        return None
    if calibration.window is not None:
        return None
    phase = next((p for p in calibration.phases or () if p.name == TRANSIENT_STAGE), None)
    if phase is None or phase.window is not None:
        return None
    start = getattr(time, "start_datetime", None)
    if start is None:
        return None
    end = getattr(time, "end_datetime", None)
    if _date_past_the_spin_up(start, end) is None:
        return (
            f"[simulation.time] ends on {pd.Timestamp(end):%Y-%m-%d}, within one year of "
            f"its start {pd.Timestamp(start):%Y-%m-%d}, so nothing lies past the spin-up "
            "to score. Lengthen the run, or write [calibration.protocol].window "
            "to say what it scores."
        )
    return (
        f"the {TRANSIENT_STAGE} phase this file writes has no window, so the "
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
    default_window: Mapping[str, str] | None = None,
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
        "max_trials": opts.steady_max_trials,
        "parameters": [opts.conductivity],
        "objective_blocks": [NETWORK_BLOCK],
        "freeze_on_success": True,
        "regime": "steady",
    }
    if opts.steady_window is not None:
        steady["steady_window"] = dict(opts.steady_window)
    if opts.steady_precision is not None:
        steady["precision"] = float(opts.steady_precision)
    if opts.steady_method_options:
        steady["method_options"] = dict(opts.steady_method_options)
    if not opts.storage:
        return [steady]

    # The window bounds every block the phase scores. The protocol scores its
    # network output in stage one alone, in one state, so the hydrograph is the
    # only block it leaves the spin-up year out of: stage one is steady, which an
    # extent table is refused on (the two-bound mode is outside the protocol).
    scored = ""
    if opts.window is None and default_window is not None:
        if default_window.get("end") is None:
            scored = (
                f", scored from {default_window['start']} on, the first year of the run "
                "left out as spin-up"
            )
        else:
            scored = (
                f", scored over [metrics] window, {default_window['start']} to "
                f"{default_window['end']}"
            )
    transient: dict[str, Any] = {
        "name": TRANSIENT_STAGE,
        "description": (
            f"Read {opts.storage} from the observed hydrograph, "
            f"{opts.conductivity} frozen, transient{scored}."
        ),
        "method": opts.transient_method,
        "max_trials": opts.transient_max_trials,
        "parameters": [opts.storage],
        "depends_on": STEADY_STAGE,
        "regime": "transient",
    }
    if scores_a_known_station:
        transient["objective_blocks"] = [HYDROGRAPH_BLOCK]
    else:
        # No station resolves here (see _resolve_observed_station), so this route
        # is only reached with several stations loaded, or a source that
        # discovers its own at load time; discharge_target refuses the former
        # by name.
        transient["variable"] = opts.discharge_variable
        transient["objective"] = opts.transient_metric
    if opts.transient_precision is not None:
        transient["precision"] = float(opts.transient_precision)
    if opts.transient_method_options:
        transient["method_options"] = dict(opts.transient_method_options)
    if opts.window is not None:
        transient["window"] = opts.window.model_dump(exclude_none=True)
    elif default_window is not None:
        transient["window"] = dict(default_window)
    return [steady, transient]


def options_the_recipe_already_runs(
    opts: MatchingHydrographicNetworkOptions,
    calibration: Any,
    time: Any,
    *,
    metrics_window: Any = None,
) -> frozenset[str]:
    """Return the options a file wrote to the value the recipe runs anyway.

    The recipe leaves a stage's method options and its precision to the method,
    and its scoring window to ``[metrics] window``, or to the run's first year
    without one. A file that writes the same thing out, ``sweep_points = 7``
    beside a bisection whose default is seven, has not moved off the recipe, and
    ``hmp check`` must not say it has. ``calibration`` is the
    validated ``[calibration]`` section, ``time`` ``[simulation.time]`` and
    ``metrics_window`` ``[metrics] window``, a mapping or the validated model.
    """
    same = set(opts.stage_options_run_as_their_method_does())
    if opts.window is not None and _is_the_default_window(
        opts.window.model_dump(exclude_none=True), calibration, time, metrics_window
    ):
        same.add("window")
    return frozenset(same)


def _is_the_default_window(
    window: Mapping[str, Any], calibration: Any, time: Any, metrics_window: Any
) -> bool:
    """Say whether a declared window scores what the recipe's own window scores.

    The recipe's window is ``[metrics] window``, less ``validation_window``, when it
    writes both bounds (:func:`_transient_window_by_default`), else one year after the run starts
    to its end. It is only the recipe's when nothing on ``[calibration]``
    bounds the scoring.
    """
    if getattr(calibration, "window", None) is not None:
        return False
    run_window = window_of_the_run(
        _raw_window(metrics_window), getattr(calibration, "validation_window", None)
    )
    if run_window is not None:
        return _is_window(window, run_window)
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


def _raw_window(window: Any) -> Mapping[str, Any] | None:
    """Return ``[metrics] window`` as a raw mapping, from a mapping or its model."""
    if window is None or isinstance(window, Mapping):
        return window
    return {"start": getattr(window, "start", None), "end": getattr(window, "end", None)}


__all__ = [
    "DEFAULTS_BY_VERSION",
    "HYDROGRAPH_BLOCK",
    "HYDROGRAPH_OUTPUT",
    "NETWORK_BLOCK",
    "STEADY_STAGE",
    "TRANSIENT_STAGE",
    "MatchingHydrographicNetwork",
    "options_the_recipe_already_runs",
    "why_the_spin_up_year_is_scored",
]
