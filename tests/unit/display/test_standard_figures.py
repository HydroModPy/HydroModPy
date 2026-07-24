"""Behavioral coverage for standard display figures."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.concentration_map import ConcentrationMap
from hydromodpy.display.figures.cross_section import CrossSection
from hydromodpy.display.figures.difference_map import DifferenceMap
from hydromodpy.display.figures.duration_curve import DurationCurveFigure
from hydromodpy.display.figures.ensemble_band import EnsembleBandFigure
from hydromodpy.display.figures.hydrograph import Hydrograph
from hydromodpy.display.figures.hydrograph_sim_obs import HydrographSimObs
from hydromodpy.display.figures.particle_tracks import ParticleTracks
from hydromodpy.display.figures.piezometric_map import PiezometricMap
from hydromodpy.display.figures.recession import RecessionCurveFigure
from hydromodpy.display.figures.recharge_map import RechargeMap
from hydromodpy.display.figures.residuals import Residuals
from hydromodpy.display.figures.scatter_one_to_one import ScatterOneToOne
from hydromodpy.display.figures.seasonal_boxplot import SeasonalBoxplotFigure
from hydromodpy.display.figures.seepage_map import SeepageMap
from hydromodpy.display.figures.side_by_side_map import SideBySideMapFigure
from hydromodpy.display.figures.water_budget import WaterBudget, _budget_unit_label
from hydromodpy.display.png_metadata import read_png_metadata


class _CatalogBackend:
    def query(self, sql, params):
        del sql, params
        return pd.DataFrame({"crs_epsg": [2154]})


class _Catalog:
    backend = _CatalogBackend()


class _Run:
    def __init__(
        self,
        *,
        sim_id: str = "sim-a",
        name: str = "baseline",
        values: np.ndarray | None = None,
    ) -> None:
        self.sim_id = sim_id
        self.id = sim_id
        self._sim_id = sim_id
        self.name = name
        self.n_timesteps = 3
        self._catalog = _Catalog()
        self.mesh = SimpleNamespace(
            vertices=np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [1.0, 1.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [2.0, 0.0, 0.0],
                    [2.0, 1.0, 0.0],
                ]
            ),
            face_node_connectivity=np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int),
        )
        self._values = np.asarray(values if values is not None else [10.0, 12.0], dtype=float)
        self._series = pd.Series(
            [2.0, 1.5, 1.0, 2.5, 1.2, 0.8],
            index=pd.date_range("2020-01-01", periods=6, freq="D"),
            name="discharge",
        )

    def timeseries(self, variable: str, *, station: str = "_catchment") -> pd.Series:
        if variable != "discharge" or station != "_catchment":
            raise KeyError(variable)
        return self._series.copy()

    def observed(self, variable: str, *, station: str = "_catchment") -> pd.DataFrame:
        del station
        dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-04"])
        return pd.DataFrame(
            {
                "datetime": dates,
                "station_id": ["obs-a", "obs-a", "obs-a"],
                "variable": [variable, variable, variable],
                "value": [1.5, 1.0, 2.0],
            }
        )

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["RCH", "RCH", "DRN"],
                "flux_in": [1.0, 2.0, 0.0],
                "flux_out": [0.0, 0.0, 1.25],
                "unit": ["m3/s", "m3/s", "m3/s"],
            }
        )

    def field(self, variable: str, **kwargs) -> np.ndarray:
        del kwargs
        if variable == "head":
            return np.asarray([[10.0, 11.0], [9.0, 10.0]])
        if variable in {
            "watertable_elevation",
            "watertable_depth",
            "concentration",
            "seepage_mask",
        }:
            return self._values.copy()
        if variable == "topography":
            return self._values + 5.0
        if variable == "recharge":
            return self._values.reshape(1, -1)
        raise KeyError(variable)

    def has_field(self, variable: str, **kwargs) -> bool:
        del kwargs
        try:
            self.field(variable)
        except KeyError:
            return False
        return True

    def has_table(self, table: str) -> bool:
        return table in {"timeseries", "budgets"}

    @property
    def time_index(self) -> pd.DatetimeIndex:
        return pd.date_range("2020-01-01", periods=self.n_timesteps, freq="D")

    def geographic(self, name: str):
        raise KeyError(name)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def test_hydrograph_uses_station_series_and_log_axis(mpl) -> None:
    fig, ax = mpl.subplots()

    Hydrograph().render(_Run(), ax, log_y=True)

    assert ax.get_yscale() == "log"
    assert ax.lines[0].get_ydata().tolist() == [2.0, 1.5, 1.0, 2.5, 1.2, 0.8]
    assert "Hydrograph" in ax.get_title()
    mpl.close(fig)


def test_duration_curve_sorts_descending_and_uses_exceedance_probability(mpl) -> None:
    fig, ax = mpl.subplots()

    DurationCurveFigure().render(_Run(), ax, log_y=False)

    x_data = ax.lines[0].get_xdata()
    y_data = ax.lines[0].get_ydata()
    assert x_data[0] == pytest.approx(100.0 / 7.0)
    assert y_data.tolist() == [2.5, 2.0, 1.5, 1.2, 1.0, 0.8]
    assert ax.get_xlim() == (0.0, 100.0)
    mpl.close(fig)


def test_seasonal_boxplot_places_one_box_per_month(mpl) -> None:
    fig, ax = mpl.subplots()

    SeasonalBoxplotFigure().render(_Run(), ax)

    assert [label.get_text() for label in ax.get_xticklabels()] == [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    assert "Seasonal distribution" in ax.get_title()
    mpl.close(fig)


def test_recession_curve_extracts_only_decreasing_limbs(mpl) -> None:
    fig, ax = mpl.subplots()

    RecessionCurveFigure().render(_Run(), ax, min_length=3)

    assert len(ax.lines) == 2
    assert ax.lines[0].get_ydata().tolist() == [2.0, 1.5, 1.0]
    assert ax.lines[1].get_ydata().tolist() == [2.5, 1.2, 0.8]
    assert "(2 limbs)" in ax.get_title()
    mpl.close(fig)


def test_water_budget_groups_components_and_labels_units(mpl) -> None:
    fig, ax = mpl.subplots()

    WaterBudget().render(_Run(), ax)

    assert "m3/s" in ax.get_ylabel()
    assert _budget_unit_label(_Run().budget()) == "m3/s"
    mixed = pd.DataFrame({"unit": ["m3/s", "m/day"]})
    assert _budget_unit_label(mixed) == "mixed units"
    mpl.close(fig)


def test_sim_obs_figures_align_only_overlapping_samples(mpl, tmp_path) -> None:
    run = _Run()

    fig, ax = mpl.subplots()
    HydrographSimObs().render(run, ax)
    assert [line.get_label() for line in ax.lines] == ["sim", "obs (obs-a)"]
    assert ax.lines[1].get_ydata().tolist() == pytest.approx([1.5, 1.0, 1.0, 2.0, 2.0])
    mpl.close(fig)

    fig, ax = mpl.subplots()
    ScatterOneToOne().render(run, ax)
    assert any("n=3" in text.get_text() for text in ax.texts)
    mpl.close(fig)

    path = tmp_path / "residuals.png"
    fig = Residuals().plot(run, bins=4, save_path=path)
    assert path.exists()
    assert len(fig.axes) == 2
    mpl.close(fig)


def test_sim_obs_figures_reject_missing_overlap(mpl) -> None:
    class _NoOverlapRun(_Run):
        def observed(self, variable: str, *, station: str = "_catchment") -> pd.DataFrame:
            del variable, station
            return pd.DataFrame(
                {
                    "datetime": pd.to_datetime(["2030-01-01"]),
                    "station_id": ["obs-a"],
                    "value": [1.0],
                }
            )

    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="No observed 'discharge' values overlap"):
        HydrographSimObs().render(_NoOverlapRun(), ax)
    mpl.close(fig)

    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="no overlapping sim/obs samples"):
        ScatterOneToOne().render(_NoOverlapRun(), ax)
    mpl.close(fig)


def test_hydrograph_sim_obs_fetches_gauge_obs_not_sim_station(mpl) -> None:
    """Sim discharge is keyed by the ``_catchment`` pseudo-station while obs
    come from a real gauge with its own id. The overlay must fetch obs across
    stations, not filter them by the sim station (which would return nothing).
    """

    class _GaugeRun(_Run):
        def observed(self, variable: str, station: str | None = None) -> pd.DataFrame:
            if station is not None:
                raise ValueError(f"No observations for station={station!r}")
            dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-04"])
            return pd.DataFrame(
                {
                    "datetime": dates,
                    "station_id": ["NANCON", "NANCON", "NANCON"],
                    "variable": [variable, variable, variable],
                    "value": [1.5, 1.0, 2.0],
                }
            )

    fig, ax = mpl.subplots()
    HydrographSimObs().render(_GaugeRun(), ax)
    assert [line.get_label() for line in ax.lines] == ["sim", "obs (NANCON)"]
    mpl.close(fig)


def test_hydrograph_sim_obs_marks_single_sample_series(mpl) -> None:
    """A steady run has one stress period; a single-point line is invisible, so
    the lone sim and obs samples must be drawn with a marker."""

    class _SteadyRun(_Run):
        def timeseries(self, variable: str, *, station: str = "_catchment") -> pd.Series:
            return pd.Series([1.8], index=pd.to_datetime(["2000-06-15"]), name="discharge")

        def observed(self, variable: str, station: str | None = None) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "datetime": pd.to_datetime(["2000-06-15"]),
                    "station_id": ["NANCON"],
                    "variable": [variable],
                    "value": [1.5],
                }
            )

    fig, ax = mpl.subplots()
    HydrographSimObs().render(_SteadyRun(), ax)
    assert [line.get_label() for line in ax.lines] == ["sim", "obs (NANCON)"]
    assert ax.lines[0].get_marker() == "o"
    assert ax.lines[1].get_marker() == "o"
    mpl.close(fig)


def test_ensemble_band_uses_quantiles_and_observed_overlay(mpl) -> None:
    fig, ax = mpl.subplots()
    members = [_Run(values=np.asarray([1.0, 2.0])), _Run(values=np.asarray([2.0, 3.0]))]
    observed = pd.Series([1.5, 1.4], index=pd.date_range("2020-01-01", periods=2))

    EnsembleBandFigure().render(members, ax, observed=observed, q_low=0.25, q_high=0.75)

    assert [line.get_label() for line in ax.lines] == ["median", "observed"]
    assert "2 runs" in ax.get_title()
    mpl.close(fig)


def test_spatial_figures_render_face_collections_and_titles(mpl) -> None:
    cases = [
        (PiezometricMap(), _Run(values=np.asarray([10.0, 12.0])), "Water-table elevation"),
        (RechargeMap(), _Run(values=np.asarray([3.0, 3.0])), "uniform"),
        (SeepageMap(), _Run(values=np.asarray([0.0, 1.0])), "Seepage areas"),
        (ConcentrationMap(), _Run(values=np.asarray([0.1, 0.2])), "Concentration"),
    ]

    for figure, run, expected_title in cases:
        fig, ax = mpl.subplots()
        figure.render(run, ax)
        assert len(ax.collections) >= 1
        assert expected_title in ax.get_title()
        mpl.close(fig)

    fig, ax = mpl.subplots()
    RechargeMap().render(_Run(values=np.asarray([3.0, 4.0])), ax)
    assert "uniform" not in ax.get_title()
    mpl.close(fig)


def test_comparison_maps_validate_reference_and_shared_ranges(mpl) -> None:
    run = _Run(sim_id="sim-a", values=np.asarray([10.0, 12.0]))
    reference = _Run(sim_id="sim-b", values=np.asarray([9.0, 11.0]))

    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="reference"):
        DifferenceMap().render(run, ax)
    mpl.close(fig)

    fig, ax = mpl.subplots()
    DifferenceMap().render(run, ax, reference=reference, field="watertable_elevation")
    assert ax.collections[0].get_array().tolist() == pytest.approx([1.0, 1.0])
    mpl.close(fig)

    fig = SideBySideMapFigure().plot(run, reference=reference, field="watertable_elevation")
    data_axes = [axis for axis in fig.axes if axis.get_title()]
    assert len(data_axes) == 2
    assert data_axes[0].collections[0].get_clim() == (9.0, 12.0)
    assert data_axes[1].collections[0].get_clim() == (9.0, 12.0)
    mpl.close(fig)


def test_cross_section_samples_topography_and_watertable_along_a_line(mpl) -> None:
    fig, ax = mpl.subplots()

    # The stub mesh spans x in [0, 2], y in [0, 1]; the section runs west to
    # east through the mesh centre and must sample both faces.
    CrossSection().render(_Run(), ax, line=[0.0, 0.5, 2.0, 0.5])

    labels = [line.get_label() for line in ax.lines]
    assert "Topography" in labels
    assert "Water table" in labels
    topography = ax.lines[labels.index("Topography")].get_ydata()
    watertable = ax.lines[labels.index("Water table")].get_ydata()
    # Topography is watertable + 5 in the stub, so the section is unsaturated
    # everywhere and the two curves never cross.
    assert np.nanmin(topography - watertable) == pytest.approx(5.0)
    assert ax.get_xlabel() == "Distance along section (m)"
    mpl.close(fig)


def test_particle_tracks_draws_valid_tracks(monkeypatch, mpl) -> None:
    import hydromodpy.display.figures.particle_tracks as module

    monkeypatch.setattr(
        module,
        "read_particle_tracks",
        lambda sim: [np.asarray([[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, -1.0, 10.0]])],
    )
    monkeypatch.setattr(module, "particle_time_to_days", lambda sim: 1.0)
    fig, ax = mpl.subplots()

    ParticleTracks().render(_Run(), ax, overlays=[])

    segments = ax.collections[0].get_segments()
    assert segments[0][:, 0].tolist() == [0.0, 1.0]
    assert ax.get_aspect() == 1.0
    mpl.close(fig)


def test_base_figure_plot_writes_png_metadata(mpl, tmp_path) -> None:
    path = tmp_path / "hydrograph.png"

    fig = Hydrograph().plot(_Run(), save_path=path, variable="discharge", timestep=2)

    try:
        info = read_png_metadata(path)
        assert info["sim_id"] == "sim-a"
        assert info["field"] == "discharge"
        assert info["time"] == "2"
        assert info["crs_epsg"] == "2154"
    finally:
        mpl.close(fig)
