"""The figure registry: catalog, renames, options, overrides and empty runs."""

from __future__ import annotations

import datetime
import inspect
import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.display import figure_registry
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import (
    BaseFigure,
    Figure,
    FigureSpec,
    options_of,
)
from hydromodpy.display.figure_options import COMMON_OPTIONS
from hydromodpy.display.figure_registry import (
    figure_option_names,
    get,
    list_figures,
    names,
)
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures import sfr_reach_timeseries
from hydromodpy.display.figures.difference_map import DifferenceMap
from hydromodpy.display.figures.piezometric_map import PiezometricMap
from hydromodpy.display.figures.side_by_side_map import SideBySideMapFigure
from hydromodpy.display.runs import figure_options_from_run, render_figure

from .test_standard_figures import _Run

# Unit tests for the figure registry and Figure protocol.

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


def test_all_expected_figures_registered():
    assert EXPECTED_FIGURES.issubset(set(names()))


def test_list_figures_returns_specs():
    specs = list_figures()
    assert len(specs) >= len(EXPECTED_FIGURES)
    for spec in specs:
        assert isinstance(spec, FigureSpec)
        assert spec.name == spec.name.lower()


def test_get_returns_protocol_compatible_instance():
    fig = get("piezometric_map")
    assert isinstance(fig, BaseFigure)
    assert isinstance(fig, Figure)
    assert fig.spec.name == "piezometric_map"


def test_get_unknown_name_raises():
    with pytest.raises(KeyError):
        get("not_a_real_figure")


def test_every_figure_has_render_method():
    for spec in list_figures():
        fig = get(spec.name)
        assert callable(getattr(fig, "render", None))
        assert callable(getattr(fig, "plot", None))


def test_spec_kind_is_valid():
    valid = {
        "spatial",
        "section",
        "timeseries",
        "balance",
        "particles",
        "table",
        "comparison",
        "animation",
    }
    for spec in list_figures():
        assert spec.kind in valid


def test_get_returns_fresh_instances():
    a = get("hydrograph")
    b = get("hydrograph")
    assert a is not b


# Renaming a figure must not break the project files that list it.
#
# A figure name is written in ``[display].figures`` and validated against the
# registry, so a rename is a hard refusal for every project that already asks for
# it. Nothing said a figure used to be called something else, which is why a name
# that says the wrong thing tends to keep it.
#
# The seam is the same one configuration keys use: the figure declares what it was
# called, the old name still resolves, and using it warns with both names.


def test_the_current_name_resolves_without_a_word() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (
            figure_registry.resolve("matching_hydrographic_network_card")
            == "matching_hydrographic_network_card"
        )


def test_the_former_name_still_resolves() -> None:
    with pytest.warns(DeprecationWarning):
        assert (
            figure_registry.resolve("abherve_two_stage_card")
            == "matching_hydrographic_network_card"
        )


def test_the_warning_names_both() -> None:
    with pytest.warns(DeprecationWarning) as caught:
        figure_registry.resolve("abherve_two_stage_card")

    message = str(caught[0].message)
    assert "abherve_two_stage_card" in message
    assert "matching_hydrographic_network_card" in message


def test_an_unknown_name_is_still_refused() -> None:
    with pytest.raises(KeyError):
        figure_registry.resolve("no_such_figure")


def test_only_current_names_are_listed() -> None:
    listed = set(figure_registry.names())

    assert "matching_hydrographic_network_card" in listed
    assert "abherve_two_stage_card" not in listed


def test_getting_the_figure_by_its_former_name_returns_the_figure() -> None:
    with pytest.warns(DeprecationWarning):
        figure = figure_registry.get("abherve_two_stage_card")

    assert figure.spec.name == "matching_hydrographic_network_card"


def test_a_display_section_listing_the_former_name_loads_and_is_rewritten() -> None:
    """Downstream sees one name, so nothing has to know about the other."""
    with pytest.warns(DeprecationWarning):
        cfg = DisplayConfig(figures=["abherve_two_stage_card"])

    assert cfg.figures == ["matching_hydrographic_network_card"]


def test_a_display_section_still_refuses_a_typo() -> None:
    with pytest.raises(ValueError, match="unknown figure"):
        DisplayConfig(figures=["abherve_two_stage_crad"])


# Every figure option says what it does, and every figure takes a title.
#
# An option is a keyword parameter of a figure's ``render`` or ``plot``. Its
# type, default, description and unit are declared on that parameter, and the
# catalog of figures reads them from there. 63 of 70 figures had no word for
# their options: this guards that none slips back.


def _named_run(sim_id: str, name: str, values: list[float]) -> _Run:
    """A run as the catalog serves it: a sim_id and a name, no ``id``."""
    run = _Run(sim_id=sim_id, name=name, values=np.asarray(values))
    del run.id
    return run


@pytest.mark.parametrize("name", [spec.name for spec in list_figures()])
def test_every_option_of_every_figure_is_described(name: str) -> None:
    options = options_of(type(get(name)))

    assert {option.name for option in options} == set(figure_option_names(name))
    undescribed = [option.name for option in options if not option.description.strip()]
    assert not undescribed, f"{name}: options without a description: {undescribed}"
    assert set(COMMON_OPTIONS) <= {option.name for option in options}


def test_type_and_default_come_from_the_signature() -> None:
    options = {option.name: option for option in options_of(DifferenceMap)}

    assert options["cmap"].type == "str"
    assert options["cmap"].default == "'RdBu_r'"
    assert options["reference"].python_only
    assert options["time"].type == 'date, "first" or "last"'
    assert options["figsize"].unit == "in"


def test_the_catalog_reads_the_declared_options() -> None:
    from tools.docs.catalogs import figures

    rows = {row["name"]: row for row in figures()}
    tolerance = {o["name"]: o for o in rows["hydrographic_network_comparison"]["option_details"]}

    assert tolerance["tolerance_m"]["unit"] == "m"
    assert tolerance["tolerance_m"]["default"] == "50.0"
    assert tolerance["tolerance_m"]["doc"]
    assert all(o["doc"] for row in rows.values() for o in row["option_details"])


def test_the_difference_map_names_both_runs_and_never_an_id(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])
    fig, ax = mpl.subplots()

    DifferenceMap().render(run, ax, reference=reference, field="watertable_elevation")

    title = ax.get_title()
    assert "wet_year" in title
    assert "dry_year" in title
    assert "1f0c" not in title
    assert "9b7e" not in title


def test_a_comparison_without_a_reference_is_skipped_not_failed(mpl) -> None:
    from hydromodpy.display.figure import FigureNotApplicable

    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    fig, ax = mpl.subplots()

    with pytest.raises(FigureNotApplicable, match="reference"):
        DifferenceMap().render(run, ax)
    with pytest.raises(FigureNotApplicable, match="reference"):
        SideBySideMapFigure().plot(run)


def test_show_run_name_off_keeps_the_run_out_of_every_title(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])

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


def test_title_replaces_the_main_title_and_an_empty_one_removes_it(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])

    titled = PiezometricMap().plot(run, title="Water table, October 2002")
    untitled = PiezometricMap().plot(run, title="")
    pair = SideBySideMapFigure().plot(
        run, reference=reference, field="watertable_elevation", title="Two runs"
    )

    assert titled.axes[0].get_title() == "Water table, October 2002"
    assert untitled.axes[0].get_title() == ""
    assert pair.get_suptitle() == "Two runs"


def test_render_figure_accepts_the_common_options(mpl, tmp_path) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])

    fig = render_figure("piezometric_map", run, save=tmp_path, title="Heads", show_run_name=False)

    assert fig.axes[0].get_title() == "Heads"
    assert (tmp_path / "piezometric_map.png").is_file()


# A key a figure does not take is refused when the config loads.
#
# Every figure ``render`` ends with a ``**`` parameter, so ``timstep = 33`` in
# ``[display.overrides.seepage_map]`` used to pass ``hmp config check`` and draw
# the last step without a word. The accepted keys are read off the figure's own
# ``plot`` and ``render`` signatures, so the check needs no second declaration
# that could drift from the code.

REGISTERED = sorted(names())


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
def test_a_misspelt_key_is_refused_with_the_keys_the_figure_takes(figure: str) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={figure: {"timstep": 33}})

    message = str(caught.value)
    assert f"[display.overrides.{figure}] has no option 'timstep'" in message
    assert ", ".join(sorted(figure_option_names(figure))) in message


def test_the_figures_that_draw_one_instant_take_time() -> None:
    instant = {name for name in REGISTERED if "time" in figure_option_names(name)}

    assert {"seepage_map", "cross_section", "piezometric_map"} <= instant
    assert "hydrograph" not in instant
    with pytest.raises(ValidationError, match="hydrograph takes: figsize, log_y"):
        DisplayConfig(overrides={"hydrograph": {"time": "last"}})


def test_a_key_under_a_misplaced_table_header_is_refused() -> None:
    # In TOML a table header swallows every key below it: `figures` written
    # after [display.overrides.seepage_map] lands in that table.
    with pytest.raises(ValidationError, match="has no option 'figures'"):
        DisplayConfig(overrides={"seepage_map": {"figures": ["seepage_map"]}})


@pytest.mark.parametrize(
    "table",
    [
        pytest.param({"timestep": 33, "orientation": "sn"}, id="the former key alone"),
        # A base that writes time and a calibration phase override that still
        # writes ".timestep" merge into one table holding both.
        pytest.param({"time": "2002-10-15", "timestep": 0}, id="both spellings in one table"),
    ],
)
def test_the_former_timestep_key_is_refused_as_an_option_the_figure_does_not_take(
    table: dict,
) -> None:
    # A file that writes it is refused earlier, by the loader, with the way to the doctor
    # of a 2.0.x release. A DisplayConfig built from a dict refuses it as any other key.
    with pytest.raises(ValidationError) as caught:
        DisplayConfig(overrides={"cross_section": table})

    message = str(caught.value)
    assert "[display.overrides.cross_section] has no option 'timestep'" in message
    assert "time" in message


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("2002-10-15", "2002-10-15"),
        (datetime.date(2002, 10, 15), "2002-10-15"),
        ("first", "first"),
        ("LAST", "last"),
        (33, 33),
        (-1, -1),
    ],
)
def test_a_time_takes_a_date_first_last_or_an_index(value, stored) -> None:
    gallery = DisplayConfig(time=value)
    figure = DisplayConfig(overrides={"seepage_map": {"time": value}})

    assert gallery.time == stored
    assert figure.overrides["seepage_map"]["time"] == stored


@pytest.mark.parametrize("value", ["yesterday", "October 2002", "2002-13-45", True, ["last"]])
def test_a_time_of_another_shape_is_refused(value) -> None:
    with pytest.raises(ValidationError, match="display.time"):
        DisplayConfig(time=value)
    with pytest.raises(ValidationError, match="display.overrides.seepage_map.time"):
        DisplayConfig(overrides={"seepage_map": {"time": value}})


class _SealedRun:
    """A run as ``hmp viz show`` reads it: the config snapshot it sealed."""

    def __init__(self, display: dict | None) -> None:
        full = DisplayConfig().model_dump(mode="json")
        self.config_snapshot = None if display is None else {"display": {**full, **display}}


def test_a_redraw_takes_the_options_the_run_was_drawn_with() -> None:
    run = _SealedRun({"time": "2002-10-15", "overrides": {"cross_section": {"orientation": "sn"}}})

    assert figure_options_from_run(run, "cross_section") == {
        "time": "2002-10-15",
        "orientation": "sn",
    }
    # The schema default of cmap, spelled out by every snapshot, is not a choice.
    assert figure_options_from_run(run, "hydrograph") == {}


def test_a_redraw_keeps_a_cmap_the_run_chose() -> None:
    run = _SealedRun({"cmap": "cividis"})

    assert figure_options_from_run(run, "seepage_map") == {"cmap": "cividis"}


def test_a_redraw_of_a_run_without_snapshot_takes_the_figure_defaults() -> None:
    assert figure_options_from_run(_SealedRun(None), "seepage_map") == {}


def test_a_redraw_of_a_snapshot_with_the_former_timestep_says_so_and_takes_the_defaults(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run = _SealedRun({"overrides": {"seepage_map": {"timestep": 33}}})

    with caplog.at_level(logging.WARNING):
        assert figure_options_from_run(run, "seepage_map") == {}

    assert "no longer loads" in caplog.text
    assert "has no option 'timestep'" in caplog.text


# Display figures are strictly read-only.
#
# A figure ``plot()`` call must never create a Zarr store, a DuckDB
# connection, or any file outside the figure's own save target. This test
# instantiates every registered figure class and confirms the catalog
# contract exposes no write method that display code could call.

_WRITE_TOKENS = (
    "write_",
    "save_zarr",
    "to_zarr",
    "insert",
    "execute",
)


def test_all_registered_figures_can_be_instantiated() -> None:
    for spec in list_figures():
        fig = get_figure(spec.name)
        assert fig is not None
        assert fig.spec.name == spec.name


def test_figures_do_not_call_zarr_write_apis() -> None:
    """Static scan: no figure renders-with-side-effects.

    We walk every figure's source file and confirm no line contains a
    token that would indicate a write to the storage layer. Display code
    reads via the ``Run`` interface only.
    """
    import hydromodpy.display.figures as pkg

    pkg_path = pkg.__path__[0]
    import pathlib

    offenders: list[tuple[str, str, int]] = []
    for path in pathlib.Path(pkg_path).glob("*.py"):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(src, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in _WRITE_TOKENS:
                if token in stripped.replace(" ", ""):
                    offenders.append((path.name, stripped, lineno))
    assert not offenders, "Figures must not call write APIs. Offending lines:\n" + "\n".join(
        f"  {p}:{ln}: {txt}" for p, txt, ln in offenders
    )


def test_base_figure_plot_signature_is_readonly() -> None:
    """The base plot() signature only exposes a save_path (a local file)."""
    from hydromodpy.display.figure import BaseFigure

    sig = inspect.signature(BaseFigure.plot)
    params = set(sig.parameters)
    assert "save_path" in params
    # No mutating keyword: catalog/store/zarr/duckdb must NOT be in signature.
    for banned in ("catalog", "store", "zarr", "duckdb", "connection"):
        assert banned not in params, f"BaseFigure.plot must not accept a '{banned}' parameter."


# Every registered figure refuses a run that lacks its data, with a sentence.
#
# A figure is offered only when the run has what it needs. On a run that holds
# nothing, each figure answers through ``unavailable_reason``: never a crash from
# inside ``render``, never a placeholder PNG. The one exception is a figure that
# compares the run with a second one, which ``spec`` cannot declare yet: its
# render refuses by naming the missing ``reference``.
#
# ``required_tables=("timeseries",)`` holds for any transient run, so a figure
# that draws one family of series (stream reaches, a lake, a piezometer) also
# checks that family, on a run whose table holds only the catchment discharge.

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

    def tables_dir_for(self, sim_id: str) -> Path:
        return Path("no-tables")


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
def test_a_stream_reach_figure_applies_once_the_run_routed_its_reaches(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _TransientRun(stations={"downstream_flow": ["main:1", "main:2"]})
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
