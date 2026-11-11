"""``Run.read``, ``table``, ``figure`` and ``show``, and the same on a session and a set of runs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.core.exceptions import CommandUsageError, NothingThereError
from hydromodpy.results.derive.reading import read_variable
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION

pytestmark = pytest.mark.fast


class _FakeCatalog:
    """Catalog stub: the tables directory of the run and its feature listing.

    A run reads its series rows from ``timeseries.parquet`` of its tables
    directory, never from the index, so the stub writes that file.
    """

    def __init__(
        self,
        tables_dir: Path,
        *,
        has_timeseries: bool = False,
        geographic_features: list[str] | None = None,
    ) -> None:
        self._tables_dir = tables_dir
        self._features = geographic_features or []
        if has_timeseries:
            tables_dir.mkdir(parents=True, exist_ok=True)
            write_table_atomic(
                pa.Table.from_pandas(
                    pd.DataFrame(
                        {"variable": ["discharge"], "source": ["simulated"], "value": [1.0]}
                    )
                ),
                tables_dir / "timeseries.parquet",
                kv_metadata={"hmp.schema_version": PARQUET_SCHEMA_VERSION},
            )

    def tables_dir_for(self, sim_id: str) -> Path:
        return self._tables_dir

    def list_geographic_features(self, sim_id: str) -> list[str]:
        return list(self._features)


class _FakeRun(Run):
    """Run subclass with controlled ``field``, ``timeseries`` and ``geographic`` methods."""

    def __init__(
        self,
        sim_id: str = "sim-x",
        *,
        catalog: _FakeCatalog | None = None,
        render=None,
    ) -> None:
        self._sim_id = sim_id
        self._catalog = catalog or _FakeCatalog(Path("tables.parquet"))
        self._render = render
        self.recorded: dict = {}

    @property
    def dir(self) -> Path:
        return Path("runs") / "fake"

    @property
    def metrics(self) -> pd.DataFrame:
        return pd.DataFrame({"metric": ["nse"], "value": [0.5]})

    def timeseries(self, var, *, station=None, period=None, source="simulated"):
        self.recorded["timeseries"] = {
            "var": var,
            "station": station,
            "period": period,
        }
        return pd.Series([1, 2, 3], name=var)

    def geographic(self, var):
        self.recorded["geographic"] = {"var": var}
        return "gdf"


def test_read_rejects_non_run() -> None:
    """The reader raises TypeError when it is not given a Run."""
    with pytest.raises(TypeError, match="Run object"):
        read_variable("not_a_run", "head")


def test_read_timeseries_dispatch(monkeypatch, tmp_path: Path) -> None:
    """A non-field variable falls back to timeseries."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    run = _FakeRun(catalog=_FakeCatalog(tmp_path / "tables.parquet", has_timeseries=True))
    result = run.read("discharge", sel={"station": "outlet"})
    assert isinstance(result, pd.Series)
    assert run.recorded["timeseries"] == {
        "var": "discharge",
        "station": "outlet",
        "period": None,
    }


def test_read_geographic_feature_dispatch(monkeypatch, tmp_path: Path) -> None:
    """A geographic-only variable goes through ``Run.geographic``."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    run = _FakeRun(
        catalog=_FakeCatalog(
            tmp_path / "tables.parquet", geographic_features=["watershed_polygon"]
        ),
    )
    result = run.read("watershed_polygon")
    assert result == "gdf"
    assert run.recorded["geographic"] == {"var": "watershed_polygon"}


def test_read_raises_when_variable_unknown(monkeypatch, tmp_path: Path) -> None:
    """``FieldNotFoundError`` is raised when nothing matches."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    monkeypatch.setattr(
        "hydromodpy.results.field_registry.all_names",
        lambda: ["head", "drawdown"],
    )
    run = _FakeRun(catalog=_FakeCatalog(tmp_path / "tables.parquet"))
    with pytest.raises(FieldNotFoundError):
        run.read("unknown_var")


@pytest.mark.parametrize("kind", ["series", "feature"])
def test_a_series_and_a_feature_refuse_a_time(kind: str, monkeypatch, tmp_path: Path) -> None:
    """Only a field has periods, so ``time=`` never changes the type a read gives."""
    monkeypatch.setattr("hydromodpy.results.field_registry.has", lambda name: False)
    catalog = _FakeCatalog(
        tmp_path / "tables.parquet",
        has_timeseries=kind == "series",
        geographic_features=["watershed_polygon"] if kind == "feature" else None,
    )
    name = "discharge" if kind == "series" else "watershed_polygon"
    with pytest.raises(ValueError, match="time"):
        _FakeRun(catalog=catalog).read(name, time=-1)


def test_a_table_is_read_from_the_tables_of_the_run(tmp_path: Path) -> None:
    run = _FakeRun(catalog=_FakeCatalog(tmp_path / "tables.parquet", has_timeseries=True))
    assert run.table("timeseries")["variable"].tolist() == ["discharge"]
    assert run.table("metrics")["metric"].tolist() == ["nse"]


def test_a_table_the_run_does_not_hold_is_refused_with_the_ones_it_holds(tmp_path: Path) -> None:
    run = _FakeRun(catalog=_FakeCatalog(tmp_path / "tables.parquet", has_timeseries=True))
    with pytest.raises(NothingThereError, match="no table 'budget'.*metrics, timeseries"):
        run.table("budget")


def _renderer(calls: list):
    def render(subject, name, options):
        calls.append((subject, name, dict(options)))
        return f"drawn {name}"

    return render


def test_a_figure_is_drawn_by_the_renderer_the_run_was_opened_with(tmp_path: Path) -> None:
    calls: list = []
    run = _FakeRun(render=_renderer(calls))
    assert run.figure("head_map", time="last", cmap="viridis") == "drawn head_map"
    assert calls == [(run, "head_map", {"time": "last", "cmap": "viridis"})]


def test_a_figure_keeps_save_and_dpi_for_the_renderer() -> None:
    calls: list = []
    _FakeRun(render=_renderer(calls)).figure("head_map", save="out.png", dpi=90)
    assert calls[0][2] == {"save": "out.png", "dpi": 90}


@pytest.mark.parametrize("name", ["head_map", "report"])
def test_a_run_opened_without_a_renderer_cannot_draw(name: str) -> None:
    run = _FakeRun()
    with pytest.raises(CommandUsageError, match="open it with hydromodpy.open to draw a figure"):
        run.figure(name) if name != "report" else run.show("report")


def test_show_reads_each_value_of_what_with_the_method_that_reads_it(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list = []
    run = _FakeRun(
        catalog=_FakeCatalog(tmp_path / "tables.parquet", has_timeseries=True),
        render=_renderer(calls),
    )
    monkeypatch.setattr(
        "hydromodpy.results.derive.reading.read_variable",
        lambda subject, name, **kwargs: ("read", name, kwargs),
    )
    monkeypatch.setattr(
        "hydromodpy.results.catalog.listing.profile_of_run", lambda directory: {"dir": directory}
    )
    assert run.show("table", name="metrics")["value"].tolist() == [0.5]
    expected = ("read", "head", {"time": -1, "layer": 0, "sel": None, "bbox": None})
    assert run.show("field", name="head", time=-1, layer=0) == expected
    assert run.show("series", name="discharge", sel={"station": "x"}) == (
        "read",
        "discharge",
        {"time": None, "layer": None, "sel": {"station": "x"}, "bbox": None},
    )
    assert run.show("profile") == {"dir": Path("runs") / "fake"}
    assert run.show("figure", name="head_map", dpi=72) == "drawn head_map"
    assert run.show("report", preset="dark") == "drawn report"
    assert calls[0][2] == {"dpi": 72}
    assert calls[1][1:] == ("report", {"preset": "dark"})


@pytest.mark.parametrize("what", ["summary", "point", "rank", "nothing"])
def test_show_refuses_a_value_the_run_cannot_read_and_names_those_it_can(what: str) -> None:
    with pytest.raises(CommandUsageError, match=r"is not one of table, field, series, profile"):
        _FakeRun().show(what)


@pytest.mark.parametrize("what", ["table", "field", "series", "figure"])
def test_show_asks_for_the_name_it_reads(what: str) -> None:
    with pytest.raises(CommandUsageError, match="needs name="):
        _FakeRun().show(what)


# -- a session -----------------------------------------------------------------


def _session(render=None) -> Session:
    session = object.__new__(Session)
    session._render = render
    session._dir = Path("sessions") / "calage"
    return session


def test_a_session_gives_its_two_tables_and_refuses_another(monkeypatch) -> None:
    monkeypatch.setattr(Session, "trials", property(lambda self: pd.DataFrame({"cost": [1.0]})))
    monkeypatch.setattr(Session, "profile", lambda self: pd.DataFrame({"kind": ["solve"]}))
    session = _session()
    assert session.table("trials")["cost"].tolist() == [1.0]
    assert session.table("profile")["kind"].tolist() == ["solve"]
    assert session.show("table", name="trials")["cost"].tolist() == [1.0]
    assert session.show("profile")["kind"].tolist() == ["solve"]
    with pytest.raises(NothingThereError, match="trials and profile, not 'cases'"):
        session.table("cases")


def test_a_session_draws_through_its_renderer_and_refuses_a_run_value() -> None:
    calls: list = []
    session = _session(_renderer(calls))
    assert session.figure("calibration_progress") == "drawn calibration_progress"
    assert session.show("report", strict=True) == "drawn report"
    assert calls[1][1:] == ("report", {"strict": True})
    with pytest.raises(CommandUsageError, match="is not one of table, profile, figure, report"):
        session.show("field", name="head")
    with pytest.raises(CommandUsageError, match="open it with hydromodpy.open"):
        _session().figure("calibration_progress")


def test_a_session_hands_its_renderer_to_the_session_of_a_run(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.results.session.descriptor import session_descriptor_path

    render = _renderer([])
    directory = tmp_path / "sessions" / "calage"
    directory.mkdir(parents=True)
    session_descriptor_path(directory).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "hydromodpy.results.calibration_trials.session_dir_of", lambda run: directory
    )
    session = Session.of_run(_FakeRun(render=render))
    assert session._render is render


# -- a set of runs -------------------------------------------------------------


def _set(render=None) -> RunSet:
    catalog = type("Catalog", (), {"closed": False, "render": None})()
    return RunSet([], catalog, render=render)


def test_a_set_of_runs_gives_its_tables_and_refuses_another(monkeypatch) -> None:
    monkeypatch.setattr(RunSet, "parameters", property(lambda self: pd.DataFrame({"K": [1.0]})))
    monkeypatch.setattr(RunSet, "metrics", property(lambda self: pd.DataFrame({"nse": [0.5]})))
    runs = _set()
    assert runs.table("parameters")["K"].tolist() == [1.0]
    assert runs.show("table", name="metrics")["nse"].tolist() == [0.5]
    assert runs.table("runs").empty
    with pytest.raises(NothingThereError, match="parameters, metrics and runs, not 'budget'"):
        runs.table("budget")


def test_a_set_of_runs_draws_through_its_renderer_or_the_one_of_its_catalog() -> None:
    calls: list = []
    runs = _set(_renderer(calls))
    assert runs.figure("ensemble_band", time="last") == "drawn ensemble_band"
    assert calls == [(runs, "ensemble_band", {"time": "last"})]
    catalog = type("Catalog", (), {"closed": False, "render": staticmethod(_renderer(calls))})()
    assert RunSet([], catalog).figure("ensemble_band") == "drawn ensemble_band"
    with pytest.raises(CommandUsageError, match="open it with hydromodpy.open"):
        _set().figure("ensemble_band")
    with pytest.raises(CommandUsageError, match="is not one of table, figure"):
        runs.show("report")
