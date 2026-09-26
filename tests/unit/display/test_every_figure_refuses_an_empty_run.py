"""Every registered figure refuses a run that lacks its data, with a sentence.

A figure is offered only when the run has what it needs. On a run that holds
nothing, each figure answers through ``unavailable_reason``: never a crash from
inside ``render``, never a placeholder PNG. The one exception is a figure that
compares the run with a second one, which ``spec`` cannot declare yet: its
render refuses by naming the missing ``reference``.

``required_tables=("timeseries",)`` holds for any transient run, so a figure
that draws one family of series (stream reaches, a lake, a piezometer) also
checks that family, on a run whose table holds only the catchment discharge.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import get, names

NEEDS_A_REFERENCE_RUN = {"difference_map", "side_by_side"}
"""Figures drawn from Python with ``reference=<run>``; ``spec`` cannot say so."""


class _Store:
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


class _Catalog:
    def __init__(self, groups: dict[str, dict], lakes: dict[str, dict]) -> None:
        self._groups = groups
        self._lakes = lakes

    def open_zarr(self, sim_id: str) -> _Store:
        return _Store(self._groups, self._lakes)


class _EmptyRun:
    """A run that persisted nothing, answering the way a real one does.

    Presence questions answer ``False``; a read of something absent raises the
    ``KeyError`` a catalog raises for it. ``fields`` names what ``has_field``
    reports as present, and ``groups`` what its store holds.
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
        self._catalog = _Catalog(groups or {}, lakes or {})

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


class _TransientRun(_EmptyRun):
    """A transient run whose ``timeseries`` table holds the series of ``stations``.

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
        self._stations = {"discharge": ["_catchment"], **(stations or {})}
        self._gauged = gauged or {}

    def has_table(self, table: str) -> bool:
        return table == "timeseries"

    def stations(self, variable: str) -> list[str]:
        return list(self._stations.get(variable, []))

    def observed(self, variable: str, *args, **kwargs) -> pd.DataFrame:
        if variable not in self._gauged:
            raise KeyError(variable)
        return self._gauged[variable]


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


@pytest.mark.parametrize("name", sorted(set(names()) - NEEDS_A_REFERENCE_RUN))
def test_a_figure_refuses_an_empty_run_with_a_sentence(name: str) -> None:
    reason = get(name).unavailable_reason(_EmptyRun())

    assert isinstance(reason, str) and reason.strip(), (
        f"figure '{name}' accepts a run that holds nothing, so it will crash or "
        "draw an empty PNG. Declare what it needs in its spec (required_fields, "
        "required_tables), or override unavailable_reason to check it without "
        "drawing (model: figures/hydrographic_network.py)."
    )


@pytest.mark.parametrize("name", sorted(NEEDS_A_REFERENCE_RUN))
def test_a_figure_that_compares_two_runs_names_the_missing_reference(name: str, mpl) -> None:
    _fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="reference"):
        get(name).render(_EmptyRun(), ax)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        (
            "particle_tracks",
            "run holds no particle pathline: no particle moved from its release point",
        ),
        ("residence_time_distribution", "run holds no timed particle pathline"),
    ],
)
@pytest.mark.parametrize(
    "particles",
    [{}, {"x": np.array([[5.0], [3.0]]), "y": np.array([[5.0], [3.0]])}],
    ids=["empty group", "release points only"],
)
def test_particles_that_never_moved_are_not_a_pathline(name, reason, particles) -> None:
    """``has_field("particles")`` answers yes for these runs, and the figures
    used to raise from inside ``render``."""
    run = _EmptyRun(fields=("particles",), groups={"particles": particles})

    assert get(name).unavailable_reason(run) == reason


SERIES_FIGURES = (
    "ensemble_band",
    "lake_stage_sim_obs",
    "lake_volume_sim_obs",
    "piezo_timeseries_sim_obs",
    "sfr_longitudinal_profile",
    "sfr_reach_network",
    "sfr_reach_timeseries",
)
"""Figures that declare only a ``timeseries`` table and draw one family of series."""


@pytest.mark.parametrize("name", SERIES_FIGURES)
def test_a_figure_refuses_a_run_whose_series_are_not_its_own(name: str) -> None:
    reason = get(name).unavailable_reason(_TransientRun())

    assert isinstance(reason, str) and reason.strip(), (
        f"figure '{name}' accepts a transient run that holds none of its series; "
        "check them in unavailable_reason, not in render."
    )


@pytest.mark.parametrize(
    "name", ["sfr_longitudinal_profile", "sfr_reach_network", "sfr_reach_timeseries"]
)
def test_a_stream_reach_figure_applies_once_the_run_routed_its_reaches(name: str) -> None:
    run = _TransientRun(stations={"downstream_flow": ["sfr:main:1", "sfr:main:2"]})

    assert get(name).unavailable_reason(run) is None


@pytest.mark.parametrize(
    ("name", "variable"), [("lake_stage_sim_obs", "stage"), ("lake_volume_sim_obs", "volume")]
)
def test_a_lake_figure_applies_once_the_lake_is_simulated_and_gauged(
    name: str, variable: str
) -> None:
    abacus = {"stage": [10.0, 12.0], "real_volume": [0.0, 5.0e6]}
    gauge = pd.DataFrame(
        {
            "station_id": ["lake:guerledan"],
            "datetime": pd.to_datetime(["2020-01-01"]),
            "value": [11.0],
        }
    )
    lake = {"lakes": {"guerledan": abacus}}
    simulated = _TransientRun(stations={variable: ["lake:guerledan"]}, **lake)
    gauged = _TransientRun(
        stations={variable: ["lake:guerledan"]}, gauged={"lake_level": gauge}, **lake
    )

    assert "no gauged lake level" in get(name).unavailable_reason(simulated)
    assert get(name).unavailable_reason(gauged) is None


def test_the_piezometer_figure_applies_to_head_series_and_asks_which_one(mpl) -> None:
    run = _TransientRun(stations={"head": ["obs:P1"]})
    figure = get("piezo_timeseries_sim_obs")
    _fig, ax = mpl.subplots()

    assert figure.unavailable_reason(run) is None
    with pytest.raises(ValueError, match=r"station=<id>, one of \['obs:P1'\]"):
        figure.render(run, ax)


def test_the_ensemble_figure_applies_to_a_set_of_runs() -> None:
    assert get("ensemble_band").unavailable_reason([_TransientRun(), _TransientRun()]) is None
