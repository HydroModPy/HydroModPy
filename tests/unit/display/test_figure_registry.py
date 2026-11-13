"""The figure registry: names, classes, kinds, options, overrides and empty runs.

Each figure has a name, a class, a kind and the fields a run must carry before
it can draw. A figure missing from the contract table fails, and so does a
figure added to the registry without a row there. Options are keyword
parameters of a figure's render or plot, and a config key a figure does not
take is refused when the config loads.
"""

from __future__ import annotations

import datetime
import inspect
import logging
import pathlib
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

import hydromodpy.display.figures as figures_package
from hydromodpy.display import figure_registry
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import NOT_A_RUNSET_REASON, BaseFigure, FigureSpec, options_of
from hydromodpy.display.figure_options import COMMON_OPTIONS
from hydromodpy.display.figure_registry import (
    figure_option_names,
    get,
    list_figures,
    names,
)
from hydromodpy.display.figures import sfr_reach_timeseries
from hydromodpy.display.figures.difference_map import DifferenceMap
from hydromodpy.display.figures.piezometric_map import PiezometricMap
from hydromodpy.display.figures.side_by_side_map import SideBySideMapFigure
from hydromodpy.display.runs import figure_options_from_run, render_figure
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.results.run.group import RunSet

EXPECTED_FIGURES = {
    "concentration_map",
    "cross_section",
    "difference_map",
    "hydrograph",
    "hydrographic_network_comparison",
    "hydrographic_network_generated_extra_only",
    "hydrographic_network_generated",
    "hydrographic_network_reference_missing_only",
    "hydrographic_network_reference",
    "particle_tracks",
    "piezometric_map",
    "recharge_map",
    "seepage_map",
    "simulated_active_network",
    "simulated_active_network_reference_overlay",
    "water_budget",
}
SPEC_KINDS = {
    "spatial",
    "section",
    "timeseries",
    "balance",
    "particles",
    "table",
    "comparison",
    "animation",
}
REGISTERED = sorted(names())
WRITE_TOKENS = ("write_", "save_zarr", "to_zarr", "insert", "execute")
# Figures drawn from Python with reference=<run>, which spec cannot say yet.
NEEDS_A_REFERENCE_RUN = {"difference_map", "side_by_side"}
# Figures that declare only a timeseries table and draw one family of series.
SERIES_FIGURES = (
    "ensemble_band",
    "lake_stage_sim_obs",
    "lake_volume_sim_obs",
    "piezo_timeseries_sim_obs",
    "sfr_longitudinal_profile",
    "sfr_reach_network",
    "sfr_reach_timeseries",
)


class TwoCellRun:
    """Two square cells 1 m wide, carrying one water-table elevation (m) per cell."""

    n_timesteps = 3

    def __init__(self, *, sim_id: str, name: str, values: list[float]) -> None:
        self.sim_id = sim_id
        self._sim_id = sim_id
        self.name = name
        self._values = np.asarray(values, dtype=float)
        self.mesh = SimpleNamespace(
            vertices=np.asarray(
                [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [2, 1, 0]], dtype=float
            ),
            face_node_connectivity=np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int),
        )

    def field(self, variable: str, **kwargs) -> np.ndarray:
        if variable == "watertable_elevation":
            return self._values.copy()
        raise KeyError(variable)

    def has_field(self, variable: str, **kwargs) -> bool:
        return variable == "watertable_elevation"

    def has_table(self, table: str) -> bool:
        return False

    def _load_row(self) -> dict:
        return {"crs_epsg": 2154}

    @property
    def time_index(self) -> pd.DatetimeIndex:
        return pd.date_range("2020-01-01", periods=self.n_timesteps, freq="D")

    def geographic(self, name: str):
        raise KeyError(name)


class SealedRun:
    """A run as ``hmp show --figure`` reads it, with the config snapshot it sealed."""

    def __init__(self, display: dict | None) -> None:
        full = DisplayConfig().model_dump(mode="json")
        self.config_snapshot = None if display is None else {"display": {**full, **display}}


class Store:
    """An opened Zarr store holding ``groups`` and the abacus of ``lakes``."""

    def __init__(self, groups: dict[str, dict], lakes: dict[str, dict]) -> None:
        self.root = groups
        self._lakes = lakes

    def lake_abacus_lakes(self) -> list[str]:
        return list(self._lakes)

    def read_lake_abacus(self, lake_id: str) -> dict:
        return self._lakes[lake_id]

    def close(self) -> None:
        return None


class Catalog:
    def __init__(self, groups: dict[str, dict], lakes: dict[str, dict]) -> None:
        self._groups = groups
        self._lakes = lakes

    def open_zarr(self, sim_id: str) -> Store:
        return Store(self._groups, self._lakes)

    def tables_dir_for(self, sim_id: str) -> Path:
        return Path("no-tables")


class EmptyRun:
    """A run that persisted nothing, answering the way a real one does.

    Presence questions answer False and a read of something absent raises the
    KeyError a catalog raises. ``fields`` names what ``has_field`` reports as
    present, and ``groups`` what its store holds.
    """

    sim_id = "00000000-0000-0000-0000-000000000000"
    _sim_id = sim_id
    id = sim_id
    name = "empty"
    solver = "modflow6"
    n_timesteps = 0

    def __init__(
        self,
        *,
        fields: tuple[str, ...] = (),
        groups: dict | None = None,
        lakes: dict | None = None,
    ) -> None:
        self._fields = fields
        self._catalog = Catalog(groups or {}, lakes or {})

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        return subgroup is None and variable in self._fields

    def has_table(self, table: str) -> bool:
        return False

    def has_hydrographic_network(self, role: str = "generated") -> bool:
        return False

    @property
    def mesh(self):
        raise KeyError("no mesh persisted for this run")

    @property
    def grid(self):
        raise KeyError("no grid persisted for this run")

    def field(self, variable: str, *args, **kwargs):
        raise KeyError(variable)

    def timeseries(self, variable: str, *args, **kwargs):
        raise KeyError(f"No timeseries for sim={self.sim_id}, var={variable}")

    def geographic(self, feature_name: str):
        raise KeyError(feature_name)

    def geographic_raster(self, name: str):
        raise KeyError(name)

    def hydrographic_network(self, role: str = "generated"):
        raise KeyError(role)


class TransientRun(EmptyRun):
    """A transient run whose timeseries table holds the series of ``stations``.

    ``gauged`` holds the observed records, keyed by variable.
    """

    def __init__(
        self,
        *,
        stations: dict[str, list[str]] | None = None,
        gauged: dict[str, pd.DataFrame] | None = None,
        lakes: dict | None = None,
    ) -> None:
        super().__init__(lakes=lakes)
        self._stations = {"discharge": ["catchment"], **(stations or {})}
        self._gauged = gauged or {}

    def has_table(self, table: str) -> bool:
        return table == "timeseries"

    def stations(self, variable: str) -> list[str]:
        return list(self._stations.get(variable, []))

    def observed(self, variable: str, *args, **kwargs) -> pd.DataFrame:
        if variable not in self._gauged:
            raise KeyError(variable)
        return self._gauged[variable]


class RunSetOf(RunSet):
    """A RunSet over runs held in memory, with no catalog behind it."""

    def __init__(self, runs: list) -> None:
        self._runs = runs
        self._sim_ids = [run.sim_id for run in runs]

    def __iter__(self):
        return iter(self._runs)


# Figure name -> (fully qualified class, spec.kind, spec.required_fields).
REGISTRY_CONTRACT: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "accumulation_map": (
        "hydromodpy.display.figures.accumulation_map.AccumulationMap",
        "spatial",
        ("drain_accumulation_flux",),
    ),
    "bisection_bracket_trace": (
        "hydromodpy.display.figures.bisection_bracket_trace.BisectionBracketTraceFigure",
        "timeseries",
        (),
    ),
    "boundary_package_map": (
        "hydromodpy.display.figures.boundary_package_map.BoundaryPackageMap",
        "spatial",
        (),
    ),
    "calibration_convergence": (
        "hydromodpy.display.figures.calibration_convergence.CalibrationConvergenceFigure",
        "timeseries",
        (),
    ),
    "calibration_landscape": (
        "hydromodpy.display.figures.calibration_landscape.CalibrationLandscapeFigure",
        "comparison",
        (),
    ),
    "calibration_objective_surface": (
        "hydromodpy.display.figures.calibration_objective_surface.CalibrationObjectiveSurfaceFigure",
        "comparison",
        (),
    ),
    "calibration_pairplot": (
        "hydromodpy.display.figures.calibration_pairplot.CalibrationPairplotFigure",
        "comparison",
        (),
    ),
    "calibration_trial_distribution": (
        "hydromodpy.display.figures.calibration_trial_distribution.CalibrationTrialDistributionFigure",
        "comparison",
        (),
    ),
    "calibration_progress": (
        "hydromodpy.display.figures.calibration_progress.CalibrationProgressFigure",
        "timeseries",
        (),
    ),
    "calibration_trace": (
        "hydromodpy.display.figures.calibration_trace.CalibrationTraceFigure",
        "timeseries",
        (),
    ),
    "concentration_map": (
        "hydromodpy.display.figures.concentration_map.ConcentrationMap",
        "spatial",
        ("concentration",),
    ),
    "concentration_boxplot": (
        "hydromodpy.display.figures.concentration_boxplot.ConcentrationBoxplot",
        "timeseries",
        ("concentration",),
    ),
    "conditioning_impact_map": (
        "hydromodpy.display.figures.conditioning_impact_map.ConditioningImpactMap",
        "comparison",
        (),
    ),
    "cross_section": (
        "hydromodpy.display.figures.cross_section.CrossSection",
        "section",
        ("watertable_elevation", "topography"),
    ),
    "depression_map": ("hydromodpy.display.figures.depression_map.DepressionMap", "spatial", ()),
    "difference_map": ("hydromodpy.display.figures.difference_map.DifferenceMap", "comparison", ()),
    "distribution": (
        "hydromodpy.display.figures.cohort_distribution.CohortDistribution",
        "table",
        (),
    ),
    "downslope_distance_crossing": (
        "hydromodpy.display.figures.downslope_distance_crossing.DownslopeDistanceCrossingFigure",
        "timeseries",
        (),
    ),
    "downslope_distance_map": (
        "hydromodpy.display.figures.downslope_distance_map.DownslopeDistanceMap",
        "spatial",
        ("release_flux",),
    ),
    "duration_curve": (
        "hydromodpy.display.figures.duration_curve.DurationCurveFigure",
        "timeseries",
        (),
    ),
    "ensemble_band": (
        "hydromodpy.display.figures.ensemble_band.EnsembleBandFigure",
        "comparison",
        (),
    ),
    "flow_direction_map": (
        "hydromodpy.display.figures.flow_direction_map.FlowDirectionMap",
        "spatial",
        (),
    ),
    "flow_intermittence_map": (
        "hydromodpy.display.figures.flow_intermittence_map.FlowIntermittenceMap",
        "spatial",
        ("release_flux",),
    ),
    "flow_persistence_map": (
        "hydromodpy.display.figures.flow_persistence_map.FlowPersistenceMap",
        "spatial",
        ("release_flux",),
    ),
    "flux_timeseries": ("hydromodpy.display.figures.flux_timeseries.FluxTimeseries", "balance", ()),
    "hydrograph": ("hydromodpy.display.figures.hydrograph.Hydrograph", "timeseries", ()),
    "hydrograph_log_nse": (
        "hydromodpy.display.figures.hydrograph_log_nse.HydrographLogNseFigure",
        "comparison",
        (),
    ),
    "hydrograph_sim_obs": (
        "hydromodpy.display.figures.hydrograph_sim_obs.HydrographSimObs",
        "comparison",
        (),
    ),
    "hydrographic_network_comparison": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkComparisonFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_generated": (
        "hydromodpy.display.figures.hydrographic_network.HydrographicNetworkGeneratedFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_generated_extra_only": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkGeneratedExtraOnlyFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_permanence": (
        "hydromodpy.display.figures.hydrographic_network.HydrographicNetworkPermanenceFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_reference": (
        "hydromodpy.display.figures.hydrographic_network.HydrographicNetworkReferenceFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_reference_missing_only": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkReferenceMissingOnlyFigure",
        "comparison",
        (),
    ),
    "lake_abacus_comparison": (
        "hydromodpy.display.figures.lake_abacus_comparison.LakeAbacusComparison",
        "comparison",
        (),
    ),
    "lake_stage_sim_obs": (
        "hydromodpy.display.figures.lake_level_sim_obs.LakeStageSimObs",
        "comparison",
        (),
    ),
    "lake_volume_sim_obs": (
        "hydromodpy.display.figures.lake_level_sim_obs.LakeVolumeSimObs",
        "comparison",
        (),
    ),
    "map": (
        "hydromodpy.display.figures.cohort_map.CohortMap",
        "table",
        (),
    ),
    "mass_balance_error": (
        "hydromodpy.display.figures.mass_balance_error.MassBalanceError",
        "balance",
        (),
    ),
    "matching_hydrographic_network_card": (
        "hydromodpy.display.figures.matching_hydrographic_network_card.MatchingHydrographicNetworkCard",
        "comparison",
        (),
    ),
    "mesh_map": ("hydromodpy.display.figures.mesh_map.MeshMap", "spatial", ("topography",)),
    "network_extent_bounds_map": (
        "hydromodpy.display.figures.network_extent_bounds_map.NetworkExtentBoundsMap",
        "comparison",
        ("release_flux",),
    ),
    "observed_network_heads_map": (
        "hydromodpy.display.figures.observed_network_heads_map.ObservedNetworkHeadsMap",
        "comparison",
        ("release_flux",),
    ),
    "parameter_cost_profile": (
        "hydromodpy.display.figures.parameter_cost_profile.ParameterCostProfileFigure",
        "timeseries",
        (),
    ),
    "parameter_map": (
        "hydromodpy.display.figures.parameter_map.ParameterMap",
        "spatial",
        ("hydraulic_conductivity",),
    ),
    "parameter_section": (
        "hydromodpy.display.figures.parameter_section.ParameterSection",
        "section",
        ("hydraulic_conductivity", "layer_thickness", "topography"),
    ),
    "particle_tracks": (
        "hydromodpy.display.figures.particle_tracks.ParticleTracks",
        "particles",
        ("particles",),
    ),
    "piezo_timeseries_sim_obs": (
        "hydromodpy.display.figures.piezo_timeseries_sim_obs.PiezoTimeseriesSimObs",
        "comparison",
        (),
    ),
    "piezometric_map": (
        "hydromodpy.display.figures.piezometric_map.PiezometricMap",
        "spatial",
        ("watertable_elevation",),
    ),
    "piper_diagram": ("hydromodpy.display.figures.piper_diagram.PiperDiagramFigure", "table", ()),
    "recession": ("hydromodpy.display.figures.recession.RecessionCurveFigure", "timeseries", ()),
    "recession_power_law": (
        "hydromodpy.display.figures.recession_power_law.RecessionPowerLaw",
        "timeseries",
        (),
    ),
    "recharge_map": (
        "hydromodpy.display.figures.recharge_map.RechargeMap",
        "spatial",
        ("recharge",),
    ),
    "residence_time_distribution": (
        "hydromodpy.display.figures.residence_time_distribution.ResidenceTimeDistribution",
        "particles",
        ("particles",),
    ),
    "residuals": ("hydromodpy.display.figures.residuals.Residuals", "comparison", ()),
    "roptim_validity_chart": (
        "hydromodpy.display.figures.roptim_validity_chart.RoptimValidityChart",
        "comparison",
        (),
    ),
    "scatter_one_to_one": (
        "hydromodpy.display.figures.scatter_one_to_one.ScatterOneToOne",
        "comparison",
        (),
    ),
    "schoeller_diagram": (
        "hydromodpy.display.figures.schoeller_diagram.SchoellerDiagramFigure",
        "table",
        (),
    ),
    "seasonal_boxplot": (
        "hydromodpy.display.figures.seasonal_boxplot.SeasonalBoxplotFigure",
        "timeseries",
        (),
    ),
    "seepage_map": (
        "hydromodpy.display.figures.seepage_map.SeepageMap",
        "spatial",
        ("seepage_mask",),
    ),
    "seepage_network_confusion_map": (
        "hydromodpy.display.figures.seepage_network_confusion_map.SeepageNetworkConfusionMap",
        "comparison",
        ("release_flux",),
    ),
    "seepage_network_reference_overlay": (
        "hydromodpy.display.figures.seepage_network_reference_overlay.SeepageNetworkReferenceOverlay",
        "comparison",
        ("release_flux",),
    ),
    "sfr_longitudinal_profile": (
        "hydromodpy.display.figures.sfr_longitudinal_profile.SfrLongitudinalProfile",
        "timeseries",
        (),
    ),
    "sfr_reach_network": (
        "hydromodpy.display.figures.sfr_reach_network.SfrReachNetwork",
        "spatial",
        (),
    ),
    "sfr_reach_timeseries": (
        "hydromodpy.display.figures.sfr_reach_timeseries.SfrReachTimeseries",
        "timeseries",
        (),
    ),
    "side_by_side": (
        "hydromodpy.display.figures.side_by_side_map.SideBySideMapFigure",
        "comparison",
        (),
    ),
    "simulated_active_network": (
        "hydromodpy.display.figures.simulated_active_network.SimulatedActiveNetworkMap",
        "spatial",
        ("drain_accumulation_flux",),
    ),
    "simulated_active_network_reference_overlay": (
        "hydromodpy.display.figures.simulated_active_network.SimulatedActiveNetworkReferenceOverlay",
        "comparison",
        ("drain_accumulation_flux",),
    ),
    "stiff_diagram": ("hydromodpy.display.figures.stiff_diagram.StiffDiagramFigure", "table", ()),
    "water_budget": ("hydromodpy.display.figures.water_budget.WaterBudget", "balance", ()),
    "watershed_id_card": (
        "hydromodpy.display.figures.watershed_id_card.WatershedIdCardFigure",
        "spatial",
        (),
    ),
    "watertable_depth_map": (
        "hydromodpy.display.figures.watertable_depth_map.WatertableDepthMap",
        "spatial",
        ("watertable_depth",),
    ),
}


def test_registry_matches_contract() -> None:
    registered = set(names())

    assert registered, "the figure registry must not be empty"
    assert registered == set(REGISTRY_CONTRACT), (
        "registry and contract have drifted apart. "
        f"registered but undeclared: {sorted(registered - set(REGISTRY_CONTRACT))}; "
        f"declared but unregistered: {sorted(set(REGISTRY_CONTRACT) - registered)}"
    )


def test_expected_figures_registered() -> None:
    assert EXPECTED_FIGURES.issubset(set(names()))


def test_list_figures_returns_specs() -> None:
    specs = list_figures()
    assert len(specs) >= len(EXPECTED_FIGURES)
    for spec in specs:
        assert isinstance(spec, FigureSpec)
        assert spec.name == spec.name.lower()


@pytest.mark.parametrize("name", REGISTERED)
def test_every_figure_is_well_formed(name: str) -> None:
    figure = get(name)

    assert figure.spec.name == name
    assert figure.spec.kind in SPEC_KINDS
    assert callable(getattr(figure, "render", None))
    assert callable(getattr(figure, "plot", None))


def test_get_returns_a_base_figure() -> None:
    figure = get("piezometric_map")

    assert isinstance(figure, BaseFigure)
    assert figure.spec.name == "piezometric_map"
    assert get("hydrograph") is not get("hydrograph")


def test_get_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        get("not_a_real_figure")


# A figure renamed in the registry keeps resolving under its former name.
CURRENT_NAME = "matching_hydrographic_network_card"
FORMER_NAME = "abherve_two_stage_card"


def test_current_name_resolves_quietly() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert figure_registry.resolve(CURRENT_NAME) == CURRENT_NAME


def test_former_name_resolves_with_warning() -> None:
    with pytest.warns(DeprecationWarning) as caught:
        assert figure_registry.resolve(FORMER_NAME) == CURRENT_NAME

    message = str(caught[0].message)
    assert FORMER_NAME in message
    assert CURRENT_NAME in message


def test_former_name_gets_the_figure() -> None:
    with pytest.warns(DeprecationWarning):
        figure = figure_registry.get(FORMER_NAME)

    assert figure.spec.name == CURRENT_NAME


def test_only_current_names_are_listed() -> None:
    listed = set(figure_registry.names())

    assert CURRENT_NAME in listed
    assert FORMER_NAME not in listed


def test_config_rewrites_a_former_name() -> None:
    # Downstream sees one name, so nothing has to know about the other.
    with pytest.warns(DeprecationWarning):
        cfg = DisplayConfig(figures=[FORMER_NAME])

    assert cfg.figures == [CURRENT_NAME]


def test_unknown_name_refused() -> None:
    with pytest.raises(KeyError, match="no_such_figure"):
        figure_registry.resolve("no_such_figure")
    with pytest.raises(ValueError, match="unknown figure"):
        DisplayConfig(figures=["abherve_two_stage_crad"])


@pytest.mark.parametrize("name", REGISTERED)
def test_every_option_is_described(name: str) -> None:
    options = options_of(type(get(name)))

    assert {option.name for option in options} == set(figure_option_names(name))
    undescribed = [option.name for option in options if not option.description.strip()]
    assert not undescribed, f"{name}: options without a description: {undescribed}"
    assert set(COMMON_OPTIONS) <= {option.name for option in options}


def test_type_and_default_from_signature() -> None:
    options = {option.name: option for option in options_of(DifferenceMap)}

    assert options["cmap"].type == "str"
    assert options["cmap"].default == "'RdBu_r'"
    assert options["reference"].python_only
    assert options["time"].type == 'date, "first" or "last"'
    assert options["figsize"].unit == "in"


def test_catalog_reads_declared_options() -> None:
    from tools.docs.catalogs import figures

    rows = {row["name"]: row for row in figures()}
    tolerance = {o["name"]: o for o in rows["hydrographic_network_comparison"]["option_details"]}

    assert tolerance["tolerance_m"]["unit"] == "m"
    assert tolerance["tolerance_m"]["default"] == "50.0"
    assert tolerance["tolerance_m"]["doc"]
    assert all(o["doc"] for row in rows.values() for o in row["option_details"])


def two_cell_runs() -> tuple[TwoCellRun, TwoCellRun]:
    """A run and a reference, with a sim_id and a name each."""
    return (
        TwoCellRun(sim_id="1f0c", name="wet_year", values=[10.0, 12.0]),
        TwoCellRun(sim_id="9b7e", name="dry_year", values=[9.0, 11.0]),
    )


def test_difference_map_names_both_runs(mpl) -> None:
    run, reference = two_cell_runs()
    _, ax = mpl.subplots()

    DifferenceMap().render(run, ax, reference=reference, field="watertable_elevation")

    title = ax.get_title()
    assert "wet_year" in title
    assert "dry_year" in title
    assert "1f0c" not in title
    assert "9b7e" not in title


def test_comparison_without_reference_skipped(mpl) -> None:
    run, _ = two_cell_runs()
    _, ax = mpl.subplots()

    with pytest.raises(FigureNotApplicable, match="reference"):
        DifferenceMap().render(run, ax)
    with pytest.raises(FigureNotApplicable, match="reference"):
        SideBySideMapFigure().plot(run)


def test_show_run_name_off_hides_it(mpl) -> None:
    run, reference = two_cell_runs()

    shown = PiezometricMap().plot(run)
    hidden = PiezometricMap().plot(run, show_run_name=False)
    pair = SideBySideMapFigure().plot(
        run, reference=reference, field="watertable_elevation", show_run_name=False
    )

    assert "wet_year" in shown.axes[0].get_title()
    assert "wet_year" not in hidden.axes[0].get_title()
    assert "Water-table elevation" in hidden.axes[0].get_title()
    titles = [axis.get_title() for axis in pair.axes if axis.get_title()]
    assert titles == ["Run", "Reference"]


def test_title_replaces_main_title(mpl) -> None:
    run, reference = two_cell_runs()

    titled = PiezometricMap().plot(run, title="Water table, October 2002")
    untitled = PiezometricMap().plot(run, title="")
    pair = SideBySideMapFigure().plot(
        run, reference=reference, field="watertable_elevation", title="Two runs"
    )

    assert titled.axes[0].get_title() == "Water table, October 2002"
    assert untitled.axes[0].get_title() == ""
    assert pair.get_suptitle() == "Two runs"


def test_render_figure_takes_common_options(mpl, tmp_path) -> None:
    run, _ = two_cell_runs()

    fig = render_figure("piezometric_map", run, save=tmp_path, title="Heads", show_run_name=False)

    assert fig.axes[0].get_title() == "Heads"
    assert (tmp_path / "piezometric_map.png").is_file()


# The accepted config keys are read off the figure's own plot and render signatures.


@pytest.mark.parametrize("figure", REGISTERED)
def test_every_key_a_figure_takes_loads(figure: str) -> None:
    accepted = figure_option_names(figure)
    assert "figsize" in accepted
    assert "timestep" not in accepted
    assert "dpi" not in accepted

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        config = DisplayConfig(overrides={figure: {key: None for key in accepted}})

    assert set(config.overrides[figure]) == set(accepted)


@pytest.mark.parametrize("figure", REGISTERED)
def test_misspelt_key_names_the_keys_taken(figure: str) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={figure: {"timstep": 33}})

    message = str(caught.value)
    assert f"[display.overrides.{figure}] has no option 'timstep'" in message
    assert ", ".join(sorted(figure_option_names(figure))) in message


def test_instant_figures_take_time() -> None:
    instant = {name for name in REGISTERED if "time" in figure_option_names(name)}

    assert {"seepage_map", "cross_section", "piezometric_map"} <= instant
    assert "hydrograph" not in instant
    with pytest.raises(ValidationError, match="hydrograph takes: figsize, log_y"):
        DisplayConfig(overrides={"hydrograph": {"time": "last"}})


def test_key_under_wrong_table_refused() -> None:
    # In TOML a table header swallows every key below it: `figures` written
    # after [display.overrides.seepage_map] lands in that table.
    with pytest.raises(ValidationError, match="has no option 'figures'"):
        DisplayConfig(overrides={"seepage_map": {"figures": ["seepage_map"]}})


FORMER_TIMESTEP_TABLES = [
    pytest.param({"timestep": 33, "orientation": "sn"}, id="the former key alone"),
    # A base that writes time and a calibration phase override that still
    # writes ".timestep" merge into one table holding both.
    pytest.param({"time": "2002-10-15", "timestep": 0}, id="both spellings in one table"),
]


@pytest.mark.parametrize("table", FORMER_TIMESTEP_TABLES)
def test_former_timestep_key_refused(table: dict) -> None:
    # A file that writes it is refused earlier, by the loader, which names the key.
    # A DisplayConfig built from a dict refuses it as any other key.
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={"cross_section": table})

    message = str(caught.value)
    assert "[display.overrides.cross_section] has no option 'timestep'" in message
    assert "time" in message


TIMES = [
    pytest.param("2002-10-15", "2002-10-15", id="date string"),
    pytest.param(datetime.date(2002, 10, 15), "2002-10-15", id="date"),
    pytest.param("first", "first", id="first"),
    pytest.param("LAST", "last", id="last in capitals"),
    pytest.param(33, 33, id="index"),
    pytest.param(-1, -1, id="negative index"),
]


@pytest.mark.parametrize(("value", "stored"), TIMES)
def test_time_forms(value, stored) -> None:
    gallery = DisplayConfig(time=value)
    figure = DisplayConfig(overrides={"seepage_map": {"time": value}})

    assert gallery.time == stored
    assert figure.overrides["seepage_map"]["time"] == stored


@pytest.mark.parametrize("value", ["yesterday", "October 2002", "2002-13-45", True, ["last"]])
def test_time_of_another_shape_refused(value) -> None:
    with pytest.raises(ValidationError, match="display.time"):
        DisplayConfig(time=value)
    with pytest.raises(ValidationError, match="display.overrides.seepage_map.time"):
        DisplayConfig(overrides={"seepage_map": {"time": value}})


def test_redraw_takes_sealed_options() -> None:
    run = SealedRun({"time": "2002-10-15", "overrides": {"cross_section": {"orientation": "sn"}}})

    assert figure_options_from_run(run, "cross_section") == {
        "time": "2002-10-15",
        "orientation": "sn",
    }
    # The schema default of cmap, spelled out by every snapshot, is not a choice.
    assert figure_options_from_run(run, "hydrograph") == {}


def test_redraw_keeps_chosen_cmap() -> None:
    run = SealedRun({"cmap": "cividis"})

    assert figure_options_from_run(run, "seepage_map") == {"cmap": "cividis"}


def test_redraw_without_snapshot() -> None:
    assert figure_options_from_run(SealedRun(None), "seepage_map") == {}


def test_redraw_with_former_timestep(caplog) -> None:
    run = SealedRun({"overrides": {"seepage_map": {"timestep": 33}}})

    with caplog.at_level(logging.WARNING):
        assert figure_options_from_run(run, "seepage_map") == {}

    assert "no longer loads" in caplog.text
    assert "has no option 'timestep'" in caplog.text


# Figures are read-only. A plot never writes a Zarr store, a DuckDB connection
# or a file outside its own save target.


def test_figures_call_no_write_api() -> None:
    offenders: list[tuple[str, str, int]] = []
    for path in pathlib.Path(figures_package.__path__[0]).glob("*.py"):
        if path.name == "__init__.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in WRITE_TOKENS:
                if token in stripped.replace(" ", ""):
                    offenders.append((path.name, stripped, lineno))
    assert not offenders, "Figures must not call write APIs. Offending lines:\n" + "\n".join(
        f"  {p}:{ln}: {txt}" for p, txt, ln in offenders
    )


def test_plot_signature_is_readonly() -> None:
    params = set(inspect.signature(BaseFigure.plot).parameters)

    assert "save_path" in params
    for banned in ("catalog", "store", "zarr", "duckdb", "connection"):
        assert banned not in params, f"BaseFigure.plot must not accept a '{banned}' parameter."


# On a run that holds nothing, each figure answers through unavailable_reason,
# never with a crash inside render and never with a placeholder PNG.


@pytest.mark.parametrize("name", sorted(set(names()) - NEEDS_A_REFERENCE_RUN))
def test_empty_run_gives_a_reason(name: str) -> None:
    reason = get(name).unavailable_reason(EmptyRun())

    assert isinstance(reason, str) and reason.strip(), (
        f"figure '{name}' accepts a run that holds nothing, so it will crash or "
        "draw an empty PNG. Declare what it needs in its spec (required_fields, "
        "required_tables), or override unavailable_reason to check it without "
        "drawing (model: figures/hydrographic_network.py)."
    )


@pytest.mark.parametrize("name", sorted(NEEDS_A_REFERENCE_RUN))
def test_comparison_names_missing_reference(name: str, mpl) -> None:
    _fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="reference"):
        get(name).render(EmptyRun(), ax)


PARTICLE_FIGURES = [
    ("particle_tracks", "run holds no particle pathline: no particle moved from its release point"),
    ("residence_time_distribution", "run holds no timed particle pathline"),
]


@pytest.mark.parametrize(("name", "reason"), PARTICLE_FIGURES)
@pytest.mark.parametrize(
    "particles",
    [{}, {"x": np.array([[5.0], [3.0]]), "y": np.array([[5.0], [3.0]])}],
    ids=["empty group", "release points only"],
)
def test_unmoved_particles_are_no_pathline(name, reason, particles) -> None:
    # has_field("particles") answers yes for these runs.
    run = EmptyRun(fields=("particles",), groups={"particles": particles})

    assert get(name).unavailable_reason(run) == reason


@pytest.mark.parametrize("name", SERIES_FIGURES)
def test_run_without_series_gives_reason(name: str) -> None:
    reason = get(name).unavailable_reason(TransientRun())

    assert isinstance(reason, str) and reason.strip(), (
        f"figure '{name}' accepts a transient run that holds none of its series; "
        "check them in unavailable_reason, not in render."
    )


@pytest.mark.parametrize(
    "name", ["sfr_longitudinal_profile", "sfr_reach_network", "sfr_reach_timeseries"]
)
def test_reach_figures_apply_when_routed(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    run = TransientRun(stations={"downstream_flow": ["main:1", "main:2"]})
    monkeypatch.setattr(
        sfr_reach_timeseries,
        "sfr_reach_links",
        lambda _run: pd.DataFrame(
            {"reach_id": ["main:1", "main:2"], "network_id": ["main"] * 2, "reach": [1, 2]}
        ),
    )

    assert get(name).unavailable_reason(run) is None


@pytest.mark.parametrize(
    ("name", "variable"), [("lake_stage_sim_obs", "stage"), ("lake_volume_sim_obs", "volume")]
)
def test_lake_figures_apply_when_gauged(name: str, variable: str) -> None:
    abacus = {"stage": [10.0, 12.0], "real_volume": [0.0, 5.0e6]}
    gauge = pd.DataFrame(
        {
            "station_id": ["lake:guerledan"],
            "datetime": pd.to_datetime(["2020-01-01"]),
            "value": [11.0],
        }
    )
    lake = {"lakes": {"guerledan": abacus}}
    simulated = TransientRun(stations={variable: ["lake:guerledan"]}, **lake)
    gauged = TransientRun(
        stations={variable: ["lake:guerledan"]}, gauged={"lake_level": gauge}, **lake
    )

    assert "no gauged lake level" in get(name).unavailable_reason(simulated)
    assert get(name).unavailable_reason(gauged) is None


def test_piezometer_figure_asks_station(mpl) -> None:
    run = TransientRun(stations={"head": ["obs:P1"]})
    figure = get("piezo_timeseries_sim_obs")
    _fig, ax = mpl.subplots()

    assert figure.unavailable_reason(run) is None
    with pytest.raises(ValueError, match=r"station=<id>, one of \['obs:P1'\]"):
        figure.render(run, ax)


def test_ensemble_needs_a_run_set() -> None:
    runs = [TransientRun(), TransientRun()]

    assert get("ensemble_band").unavailable_reason(RunSetOf(runs)) is None
    assert get("ensemble_band").unavailable_reason(runs) == NOT_A_RUNSET_REASON
