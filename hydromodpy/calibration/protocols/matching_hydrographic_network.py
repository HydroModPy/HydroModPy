"""The two-stage calibration against the mapped hydrographic network.

Where a gauge gives one series at one point, the mapped stream network gives a
spatial constraint over the whole catchment: the extent of the network the
aquifer keeps flowing is set by how much water the medium transmits, so the
agreement between the simulated seepage network and the mapped one identifies
the hydraulic conductivity without any discharge record at all. The storage
coefficient it cannot see is then read from the hydrograph, at a conductivity
held fixed.

Published in :cite:`abherve2023` and used again in :cite:`abherve2024headwater`
and :cite:`abherve2025climate`.

Stage one is steady: one period over the record, the mean recharge, and the
conductivity moved until the simulated network matches the mapped one. Stage two
is transient at the daily step, the conductivity frozen, and the storage moved
against the observed hydrograph. The order is not a convenience. A steady solve
carries no storage, so stage one is blind to it, which is exactly what makes the
conductivity identifiable there.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import Field, model_validator

from hydromodpy.calibration.protocols.base import Deviation, Reference
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import PositiveFloat

STEADY_STAGE = "steady_conductivity"
TRANSIENT_STAGE = "transient_storage"
NETWORK_BLOCK = "network_extension"


class MatchingHydrographicNetworkOptions(HydroModelBase):
    """What a file may say about the protocol beyond naming it.

    Everything here has a default that reproduces the published method. The
    names are the ones the file uses for its own parameters and outputs, and the
    engines are free: the method is the pair of criteria and the order they run
    in, not the optimizer that walks them.
    """

    name: Annotated[Literal["matching_hydrographic_network"], Profile.USER] = Field(
        description="Protocol identifier.",
    )
    version: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Recipe version this file was written against. Unset runs the version this "
            "installation carries; pinned, a mismatch is refused rather than "
            "approximated, so a result that informed a decision stays replayable."
        ),
    )
    conductivity: Annotated[str, Profile.USER] = Field(
        default="K",
        description="Name of the calibration parameter stage one moves, as the file "
        "declares it under [calibration.parameters].",
    )
    storage: Annotated[str | None, Profile.USER] = Field(
        default="Sy",
        description="Name of the calibration parameter stage two moves. Null runs the "
        "network stage alone, which is a method in its own right: it identifies the "
        "conductivity without any discharge record.",
    )
    network_output: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Name of the network output stage one is scored on. Unset picks "
        "the single output declared with support='network'.",
    )
    steady_metric: Annotated[Literal["distance_gap", "distance_mean"], Profile.USER] = Field(
        default="distance_gap",
        description="Criterion of stage one. 'distance_gap' is the signed difference "
        "of Eq. 1, whose zero is the balance the paper solves for. 'distance_mean' is "
        "the mean offset: a diagnostic, and the estimator of the reference script, "
        "whose interior minimum sits nowhere in particular.",
    )
    steady_method: Annotated[str, Profile.USER] = Field(
        default="bisection",
        description="Engine of stage one. The signed criterion crosses zero once over "
        "several decades, which is what a root search wants; any registered engine is "
        "accepted.",
    )
    steady_max_iter: Annotated[int, Profile.USER] = Field(
        default=20,
        ge=1,
        description="Evaluation budget of stage one.",
    )
    steady_tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage one has to pin the conductivity before it "
        "stops, as a relative precision on the conductivity: 0.01 is the paper's one "
        "per cent. Unset takes the engine's default, which for the bisection is that "
        "same one per cent.",
    )
    steady_engine_options: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Options of the stage-one engine itself, named as that engine "
        "names them. Which ones exist depends on steady_method, and the model of "
        "each engine is in calibration.optim.method_config. A key the engine does not "
        "know is refused before the first solver call. The escape hatch for "
        "reproducing a published call; a "
        "precision is said once, in steady_tolerance.",
    )
    steady_window: Annotated[dict[str, str] | None, Profile.USER] = Field(
        default=None,
        description="Dates the steady stage averages, as {start, end}. Unset takes the "
        "whole [simulation.time] window.",
    )
    transient_metric: Annotated[str, Profile.USER] = Field(
        default="nse_log",
        description="Criterion of stage two. The default weights recessions as heavily "
        "as peaks, which is where storage shows.",
    )
    transient_method: Annotated[str, Profile.USER] = Field(
        default="scipy_nelder_mead",
        description="Engine of stage two.",
    )
    transient_max_iter: Annotated[int, Profile.USER] = Field(
        default=120,
        ge=1,
        description="Evaluation budget of stage two.",
    )
    transient_tolerance: Annotated[PositiveFloat | None, Profile.USER] = Field(
        default=None,
        description="How precisely stage two has to pin the storage before it stops, "
        "as a relative precision on the storage coefficient.",
    )
    transient_engine_options: Annotated[dict[str, Any], Profile.DEV] = Field(
        default_factory=dict,
        description="Options of the stage-two engine itself, named as that engine "
        "names them, and refused when it does not know them. Which ones exist depends "
        "on transient_method.",
    )
    discharge_variable: Annotated[str, Profile.USER] = Field(
        default="discharge",
        description="Observed variable stage two is scored on.",
    )
    observed_station_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Gauge whose cost drives stage two. Required when several stations are loaded.",
    )
    scoring_window: Annotated[dict[str, str] | None, Profile.USER] = Field(
        default=None,
        description="Dates bounding the samples stage two scores on, as {start, end}. "
        "Use it to drop the spin-up year the transient stage still has to simulate.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_the_bare_name(cls, data: Any) -> Any:
        """``protocol = "matching_hydrographic_network"`` is the whole declaration."""
        if isinstance(data, str):
            return {"name": data}
        return data


class MatchingHydrographicNetwork:
    """Conductivity from the mapped stream network, storage from the hydrograph."""

    name = "matching_hydrographic_network"
    version = "1.0"
    title = "Matching the hydrographic network"
    summary = (
        "Two stages. The mapped stream network constrains the hydraulic conductivity "
        "in steady state, by balancing the descent from the simulated seepage network "
        "to the mapped one against its reciprocal. The specific yield, to which a "
        "steady solve is blind, is then read from the observed hydrograph with the "
        "conductivity frozen. The first stage needs no discharge record."
    )
    stages = (
        "Steady state, mean recharge over the record: move the conductivity until the "
        "simulated seepage network matches the mapped one.",
        "Transient at the forcing step, conductivity frozen: move the specific yield "
        "against the observed hydrograph.",
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
        ),
        Deviation(
            key="observed_position_accuracy",
            paper="the validity length is the DEM resolution and nothing else",
            here="unset, so the paper's reading holds unless a file states it",
            why=(
                "the positional accuracy of the mapped network does not improve "
                "because the mesh is refined, so without a floor the validity ratio "
                "follows the mesh; declaring it is a departure and is left to the file."
            ),
        ),
        Deviation(
            key="diagonal_neighbors",
            paper="the descent follows a D8 flowpath, which is what "
            "wbt.downslope_distance_to_stream traces",
            here="false by default, a descent over shared edges only, which is D4",
            why=(
                "a D4 descent cannot follow a talweg that runs diagonally across a "
                "square grid, and the delineation that produces the catchment uses a D8 "
                "pointer, so the criterion and the basin it is masked to do not descend "
                "the same way. Measured on a synthetic diagonal valley, the most "
                "accumulated cell collects 6.6 per cent of the domain under shared edges "
                "and 100 per cent under shared nodes; measured on Nancon, the cell at the "
                "basin outlet drains 0.107 of 64.631 km2. Setting it true returns to the "
                "publication and changes every result obtained without it, which is why "
                "the default has not been moved."
            ),
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
        ),
    )

    reference_values: Mapping[str, str] = {
        "roptim_max": "2, the validity bound of Eq. 4",
        "criterion": "J = D_so - D_os, Eq. 1, whose zero is the balance",
        "r_optim": "D_optim / L_ref, Eq. 3",
        "catchments": "Abherve et al. (2023) report the method on 45 Brittany catchments",
    }

    adjustable = frozenset(
        {
            "conductivity",
            "storage",
            "network_output",
            "steady_metric",
            "steady_method",
            "steady_max_iter",
            "steady_tolerance",
            "steady_engine_options",
            "steady_window",
            "transient_metric",
            "transient_method",
            "transient_max_iter",
            "transient_tolerance",
            "transient_engine_options",
            "discharge_variable",
            "observed_station_id",
            "scoring_window",
        }
    )
    """Everything the options model exposes. Changing one keeps the method; the
    record still says which values were used, because a reader comparing to the
    publication needs to know that the engine was swapped."""

    def expand(self, options: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
        """Return the document with the two stages and their objective block written."""
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

        network_output = _resolve_network_output(calibration.get("outputs") or {}, opts)
        steady_start, steady_end = _steady_window(expanded, opts)

        calibration["objective_blocks"] = [
            {
                "name": NETWORK_BLOCK,
                "metric": opts.steady_metric,
                "uses_outputs": [network_output],
            }
        ]
        calibration["phases"] = _phases(opts, steady_start=steady_start, steady_end=steady_end)
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


def _steady_window(
    document: Mapping[str, Any], opts: MatchingHydrographicNetworkOptions
) -> tuple[str, str]:
    if opts.steady_window is not None:
        window = opts.steady_window
        missing = [key for key in ("start", "end") if not window.get(key)]
        if missing:
            raise ValueError(
                "[calibration.protocol].steady_window needs both 'start' and 'end'; "
                f"missing {', '.join(missing)}."
            )
        return str(window["start"]), str(window["end"])

    time = (document.get("simulation") or {}).get("time") or {}
    start = time.get("start_datetime")
    end = time.get("end_datetime")
    if not start or not end:
        raise ValueError(
            "protocol 'matching_hydrographic_network' averages the record over one steady "
            "period and reads its span from [simulation.time], which declares no "
            "start_datetime/end_datetime here. Write them, or name the span in "
            "[calibration.protocol].steady_window."
        )
    return str(start), str(end)


def _phases(
    opts: MatchingHydrographicNetworkOptions, *, steady_start: str, steady_end: str
) -> list[dict[str, Any]]:
    span_days = (pd.Timestamp(steady_end) - pd.Timestamp(steady_start)).days + 1
    if span_days < 1:
        raise ValueError(
            f"the steady stage spans {steady_start} to {steady_end}, which is not a forward window."
        )

    steady: dict[str, Any] = {
        "name": STEADY_STAGE,
        "description": (
            "Match the simulated seepage network to the mapped one by moving "
            f"{opts.conductivity}, steady state over {steady_start}..{steady_end}."
        ),
        "method": opts.steady_method,
        "max_iter": opts.steady_max_iter,
        "parameters": [opts.conductivity],
        "objective_blocks": [NETWORK_BLOCK],
        "freeze_on_success": True,
        "overrides": {
            "flow.flow_regime": "steady",
            "simulation.time.start_datetime": steady_start,
            "simulation.time.end_datetime": steady_end,
            "simulation.time.step_unit": "day",
            "simulation.time.step_value": span_days,
        },
    }
    if opts.steady_tolerance is not None:
        steady["tolerance"] = float(opts.steady_tolerance)
    if opts.steady_engine_options:
        steady["optimizer_kwargs"] = dict(opts.steady_engine_options)
    if opts.storage is None:
        return [steady]

    transient: dict[str, Any] = {
        "name": TRANSIENT_STAGE,
        "description": (
            f"Read {opts.storage} from the observed hydrograph, "
            f"{opts.conductivity} frozen, transient."
        ),
        "method": opts.transient_method,
        "max_iter": opts.transient_max_iter,
        "parameters": [opts.storage],
        "variable": opts.discharge_variable,
        "objective": opts.transient_metric,
        "depends_on": STEADY_STAGE,
        "overrides": {"flow.flow_regime": "transient"},
    }
    if opts.transient_tolerance is not None:
        transient["tolerance"] = float(opts.transient_tolerance)
    if opts.transient_engine_options:
        transient["optimizer_kwargs"] = dict(opts.transient_engine_options)
    if opts.observed_station_id is not None:
        transient["observed_station_id"] = opts.observed_station_id
    if opts.scoring_window is not None:
        transient["scoring_window"] = dict(opts.scoring_window)
    return [steady, transient]


__all__ = [
    "NETWORK_BLOCK",
    "STEADY_STAGE",
    "TRANSIENT_STAGE",
    "MatchingHydrographicNetwork",
    "MatchingHydrographicNetworkOptions",
]
