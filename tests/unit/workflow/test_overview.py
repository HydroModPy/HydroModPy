"""The data overview: the launcher of a run that only loads data, and the inventory it writes.

The inventory has one row per family, per station and per well. Recharge is a mean in
mm/year, pumping in m3/s. The launcher resolves the DEM, the network map and the crossings file.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pyarrow as pa
import pytest
from pydantic import ValidationError

import hydromodpy.data.variables.dem.resolver as dem_resolver
import hydromodpy.data.variables.hydrography.resolver as hydrography_resolver
import hydromodpy.workflow.overview as overview_module
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.run_state import LoadedDataContext
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.variables.crossings.resolver import fill_crossings_path
from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig
from hydromodpy.data.variables.sim2_series import RunoffConfig, RunoffSourceConfig
from hydromodpy.results.storage.parquet_schemas import DATA_INVENTORY_SCHEMA
from hydromodpy.workflow.overview import DataOverviewLauncher
from tests._helpers.geographic_cases import BENCH_RIVER, outlet_document


def _overview_state(data: DataConfig, window: tuple[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            overview=SimpleNamespace(date_start=window[0], date_end=window[1]),
            data=data,
        )
    )


class _CopyableCfg(SimpleNamespace):
    """A configuration stand-in that copies like a pydantic model."""

    def model_copy(self, *, update):
        return _CopyableCfg(**{**vars(self), **update})


def _data_config(**sections) -> DataConfig:
    return DataConfig(types=list(sections), **sections)


def test_dates_fill_sections_without_a_window(tmp_path) -> None:
    data = _data_config(
        recharge=RechargeConfig(
            sources=[
                RechargeSourceConfig(
                    source="synthetic",
                    freq="MS",
                    start_date="2020-01-01",
                    periods=12,
                    values=[1.0] * 12,
                )
            ]
        ),
        runoff=RunoffConfig(
            sources=[RunoffSourceConfig(source="file", path=tmp_path / "runoff.csv")],
            date_start="2010-01-01",
            date_end="2019-12-31",
        ),
    )
    state = _overview_state(data, ("2020-01-01", "2020-12-31"))

    overview_module.DataOverviewLauncher._inject_overview_dates(state)

    assert state.cfg.data.recharge.date_start == "2020-01-01"
    assert state.cfg.data.recharge.date_end == "2020-12-31"
    assert state.cfg.data.runoff.date_start == "2010-01-01"
    assert state.cfg.data.runoff.date_end == "2019-12-31"


def test_reversed_window_is_refused() -> None:
    data = _data_config(recharge=RechargeConfig(sources=[RechargeSourceConfig(source="sim2")]))
    state = _overview_state(data, ("2020-12-31", "2020-01-01"))

    with pytest.raises(ValidationError, match="date_start must be before date_end"):
        overview_module.DataOverviewLauncher._inject_overview_dates(state)

    assert state.cfg.data.recharge.date_start is None
    assert state.cfg.data.recharge.date_end is None


def test_load_data_attaches_the_network(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeLoader:
        def __init__(self, *, config_path, data_plan, bounds) -> None:
            captured["config_path"] = config_path
            captured["bounds"] = bounds
            captured["data_plan"] = data_plan

        def load_all(self, proxy) -> None:
            captured["proxy"] = proxy
            proxy.loaded_data.loaded_by_fake_loader = True

    def fake_attach(features, hydrography):
        captured["attached"] = (features, hydrography)
        return "features-with-network"

    monkeypatch.setattr(
        "hydromodpy.data.loading.loader.DataLoader",
        FakeLoader,
    )
    monkeypatch.setattr(
        "hydromodpy.catchment.algorithms.derived_features.attach_reference_hydrographic_network",
        fake_attach,
    )

    config_path = tmp_path / "overview.toml"
    launcher = object.__new__(overview_module.DataOverviewLauncher)
    launcher.config_path = config_path
    launcher.bounds = Bounds()
    loaded_data = SimpleNamespace(hydrography="network")
    recharge = RechargeConfig(
        sources=[RechargeSourceConfig(source="file", path=tmp_path / "recharge.csv")]
    )
    state = SimpleNamespace(
        cfg=_CopyableCfg(
            data=SimpleNamespace(
                types=("recharge", "hydrography"),
                recharge=recharge,
                hydrography=SimpleNamespace(),
            ),
            workspace="workspace-config",
            overview=SimpleNamespace(date_start="2021-01-01", date_end="2021-01-31"),
            simulation="simulation-config",
        ),
        workspace="workspace-runtime",
        geographic="geographic-runtime",
        loaded_data=loaded_data,
        geographic_features="features",
    )

    launcher._load_data(state)

    proxy = captured["proxy"]
    assert captured["config_path"] == config_path
    assert captured["bounds"] is launcher.bounds
    assert captured["data_plan"].explicit_types == ("recharge", "hydrography")
    assert proxy.cfg.data is state.cfg.data
    assert proxy.cfg.workspace == "workspace-config"
    assert proxy.cfg.overview is state.cfg.overview
    assert proxy.cfg.simulation is None
    assert proxy.setup.workspace == "workspace-runtime"
    assert proxy.setup.geographic == "geographic-runtime"
    assert proxy.loaded_data is loaded_data
    assert loaded_data.loaded_by_fake_loader is True
    assert state.cfg.data.recharge.date_start == "2021-01-01"
    assert state.cfg.data.recharge.date_end == "2021-01-31"
    assert captured["attached"] == ("features", "network")
    assert state.geographic_features == "features-with-network"


def test_a_dem_is_required(tmp_path) -> None:
    state = SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(),
            data=SimpleNamespace(),
        ),
        workspace=SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data")),
        geographic=None,
        loaded_data=None,
    )

    with pytest.raises(ConfigMissingError, match=r"No \[data.dem\] source"):
        _launcher(tmp_path)._resolve_geographic_inputs(state)


def _dem_record(path: Path) -> FileRecord:
    return FileRecord(path, "0" * 64, origin="file")


def _map_state(monkeypatch, tmp_path, *, sources=()):
    dem = _dem_record(tmp_path / "dem.tif")
    monkeypatch.setattr(dem_resolver, "resolve_dem", lambda *args, **kwargs: dem)
    return SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(),
            data=SimpleNamespace(hydrography=SimpleNamespace(sources=list(sources))),
        ),
        workspace=SimpleNamespace(paths=SimpleNamespace(data_path=tmp_path / "data")),
        geographic=None,
        loaded_data=None,
    )


def _launcher(tmp_path):
    launcher = object.__new__(overview_module.DataOverviewLauncher)
    launcher.config_path = tmp_path / "overview.toml"
    launcher.bounds = Bounds()
    return launcher


NETWORK = Path("network.gpkg")

NETWORK_MAPS = [
    pytest.param([SimpleNamespace(source="file")], NETWORK, id="source gives a vector"),
    pytest.param([SimpleNamespace(source="file")], None, id="source holds no vector"),
    # Same rule as the run pipeline: no source declared, no network map.
    pytest.param([], None, id="no source declared"),
]


@pytest.mark.parametrize(("sources", "network_map"), NETWORK_MAPS)
def test_network_map_of_the_data_family(monkeypatch, tmp_path, sources, network_map):
    monkeypatch.setattr(
        hydrography_resolver, "resolve_network_map_path", lambda *args, **kwargs: network_map
    )
    state = _map_state(monkeypatch, tmp_path, sources=sources)

    assert _launcher(tmp_path)._resolve_geographic_inputs(state) == (
        network_map,
        tmp_path / "dem.tif",
    )


def test_geographic_step_gets_the_map_path(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    class _Delineation:
        def __init__(self, config, workspace, *, dem_path=None, network_map_path=None):
            seen["network_map_path"] = network_map_path
            seen["dem_path"] = dem_path

    monkeypatch.setattr(
        "hydromodpy.catchment.preprocess.catchment_delineation.CatchmentDelineation",
        _Delineation,
    )
    monkeypatch.setattr(
        "hydromodpy.catchment.algorithms.derived_features.coerce_geographic_derived_features",
        lambda geographic: None,
    )
    state = SimpleNamespace(cfg=SimpleNamespace(geographic=SimpleNamespace()), workspace=None)
    network = tmp_path / "network.gpkg"

    with pytest.raises(ConfigError):
        overview_module.DataOverviewLauncher._setup_geographic(state, network, tmp_path / "dem.tif")

    assert seen["network_map_path"] == network
    assert seen["dem_path"] == tmp_path / "dem.tif"


# [geographic.crossings] reads the file of [[data.crossings.sources]] when it has no path.
# The run setup and the overview resolve it with the same rule: when the notch or the
# bed regularization is on, and never over a declared path.

_RESOLVER = "hydromodpy.data.variables.crossings.resolver.resolve_crossings_path_from_data_sources"


_ROE = [SimpleNamespace(source="roe")]


def _geographic(section: str = "crossings", **crossings) -> GeographicConfig:
    sections = {
        "crossings": {"crossings": {"enabled": True, **crossings}},
        "bed": {"bed_regularization": {"enabled": True}},
        "off": {},
    }[section]
    return outlet_document(river_network=BENCH_RIVER, **sections)


def _cfg(geographic: GeographicConfig, sources: list | None) -> SimpleNamespace:
    crossings = None if sources is None else SimpleNamespace(sources=sources)
    return SimpleNamespace(geographic=geographic, data=SimpleNamespace(crossings=crossings))


def _resolve(entry: str, cfg: SimpleNamespace, tmp_path: Path) -> None:
    if entry == "run":
        fill_crossings_path(cfg, config_path=tmp_path / "project.toml", data_path=None)
        return
    overview = object.__new__(DataOverviewLauncher)
    overview.config_path = tmp_path / "project.toml"
    overview.bounds = Bounds()
    state = SimpleNamespace(cfg=cfg, workspace=None, geographic=None, loaded_data=None)
    record = _dem_record(tmp_path / "dem.tif")
    with mock.patch.object(dem_resolver, "resolve_dem", return_value=record):
        overview._resolve_geographic_inputs(state)


@pytest.mark.parametrize("entry", ["run", "overview"])
@pytest.mark.parametrize("section", ["crossings", "bed"])
def test_crossings_path_from_sources(entry, section, monkeypatch, tmp_path):
    merged = tmp_path / "crossings_ground_roe_12345678.gpkg"
    calls: list[Path] = []

    def resolve(cfg, *, config_path, cache_dir=None, dem_path=None):
        calls.append(config_path)
        return merged

    monkeypatch.setattr(_RESOLVER, resolve)
    cfg = _cfg(_geographic(section), _ROE)
    _resolve(entry, cfg, tmp_path)
    assert cfg.geographic.crossings.path == merged
    assert cfg.geographic.crossings.enabled is (section == "crossings")
    assert calls == [tmp_path / "project.toml"]


@pytest.mark.parametrize("entry", ["run", "overview"])
def test_crossings_path_left_alone(entry, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_RESOLVER, lambda *a, **k: pytest.fail("resolved a path"))
    own = _cfg(_geographic(path=tmp_path / "mine.gpkg"), _ROE)
    others = [_cfg(_geographic("off"), _ROE)] + [_cfg(_geographic("bed"), s) for s in (None, [])]
    for cfg in (own, *others):
        _resolve(entry, cfg, tmp_path)
    assert own.geographic.crossings.path == tmp_path / "mine.gpkg"
    assert [cfg.geographic.crossings.path for cfg in others] == [None, None, None]


@pytest.mark.parametrize(
    ("entry", "sources", "error"),
    [("run", None, ConfigError), ("run", [], ConfigError), ("overview", None, ConfigError)],
)
def test_crossings_refusals(entry, sources, error, tmp_path) -> None:
    with pytest.raises(error, match=r"crossings"):
        _resolve(entry, _cfg(_geographic(), sources), tmp_path)


def _points(station: str, start: str, end: str, *, variable="discharge", source="hubeau"):
    return SimpleNamespace(
        station_id=station,
        variable=variable,
        source=source,
        unit="m3/s",
        data=None,
        location=SimpleNamespace(
            x=1.5, y=2.5, crs="EPSG:2154", metadata={"station_name": "Naizin"}
        ),
        date_start=pd.Timestamp(start),
        date_end=pd.Timestamp(end),
    )


def _recharge(unit: str, values: list[float]):
    data = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=len(values)), "value": values}
    )
    return SimpleNamespace(
        station_id="r",
        variable="recharge",
        source="synthetic",
        unit=unit,
        data=data,
        location=None,
        date_start=pd.Timestamp("2020-01-01"),
        date_end=pd.Timestamp("2020-01-02"),
    )


def _state(loaded: dict, *, types: list[str], sections: dict | None = None, wells=None):
    sinks = None if wells is None else SimpleNamespace(wells=wells)
    return SimpleNamespace(
        cfg=SimpleNamespace(
            data=SimpleNamespace(types=types, **(sections or {})),
            flow=SimpleNamespace(sinks_sources=sinks),
        ),
        loaded_data=LoadedDataContext(**loaded),
    )


def _by(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row["row_kind"] == kind]


def test_station_rows_merge_records() -> None:
    wq = SimpleNamespace(
        points=[
            _points("WQ1", "2020-02-01", "2020-02-10", variable="nitrate"),
            _points("WQ1", "2020-01-01", "2020-03-01", variable="chloride"),
        ]
    )
    rows = overview_module.inventory_rows(_state({"water_quality": wq}, types=["water_quality"]))

    (family,) = _by(rows, "family")
    (station,) = _by(rows, "station")
    assert (family["family"], family["records"]) == ("water_quality", 2)
    assert (station["item_id"], station["records"], station["name"]) == ("WQ1", 2, "Naizin")
    assert station["first"] == datetime(2020, 1, 1, tzinfo=UTC)
    assert station["last"] == datetime(2020, 3, 1, tzinfo=UTC)
    assert station["crs_epsg"] == 2154


@pytest.mark.parametrize(
    ("unit", "values", "expected", "expected_unit"),
    [
        pytest.param("mm/day", [1.0, 1.0], 365.25, "mm/year", id="per-day-to-per-year"),
        pytest.param("mm/year", [200.0, 300.0], 250.0, "mm/year", id="kept-in-its-unit"),
    ],
)
def test_recharge_family_mean(unit, values, expected, expected_unit) -> None:
    loaded = {"recharge": SimpleNamespace(points=[_recharge(unit, values)], fields=[])}
    rows = overview_module.inventory_rows(_state(loaded, types=["recharge"]))

    (family,) = _by(rows, "family")
    assert family["mean_value"] == pytest.approx(expected)
    assert family["unit"] == expected_unit
    assert _by(rows, "station") == []


def test_unloaded_family_has_no_records() -> None:
    rows = overview_module.inventory_rows(_state({}, types=["hydrometry"]))

    assert [(r["family"], r["records"]) for r in rows] == [("hydrometry", 0)]


def test_well_rows() -> None:
    wells = {
        "a": SimpleNamespace(
            location=SimpleNamespace(x=1.0, y=2.0), flux=[-0.1, -0.3], units="m3/s"
        ),
        "b": SimpleNamespace(location=None, flux=None, units="m3/s"),
    }
    rows = overview_module.inventory_rows(_state({}, types=[], wells=wells))

    family = _by(rows, "family")[0]
    assert (family["family"], family["records"]) == ("pumping", 2)
    assert family["mean_value"] == pytest.approx(0.2)
    well_a, well_b = _by(rows, "well")
    assert (well_a["item_id"], well_a["x"], well_a["mean_value"]) == ("a", 1.0, pytest.approx(-0.2))
    assert (well_b["x"], well_b["mean_value"]) == (None, None)


def test_rows_fit_the_schema() -> None:
    wq = SimpleNamespace(points=[_points("H1", "2020-01-01", "2020-01-02")])
    wells = {"a": SimpleNamespace(location=None, flux=-1.0, units="m3/s")}
    rows = overview_module.inventory_rows(
        _state({"hydrometry": wq}, types=["hydrometry"], wells=wells)
    )

    table = pa.Table.from_pylist(
        [{**row, "sim_id": "s"} for row in rows], schema=DATA_INVENTORY_SCHEMA
    )

    key = [(r["row_kind"], r["family"], r["source"], r["item_id"]) for r in table.to_pylist()]
    assert len(key) == len(set(key)) == 4
    assert set(DATA_INVENTORY_SCHEMA.names) == {"sim_id", *rows[0]}


def test_loaded_inputs(tmp_path) -> None:
    source = tmp_path / "data" / "h1.csv"
    source.parent.mkdir()
    source.write_text("a,b\n", encoding="utf-8")
    record = _points("H1", "2020-01-01", "2020-01-02")
    record.metadata = {"source_path": str(source)}
    state = _state(
        {"hydrometry": SimpleNamespace(points=[record], fields=[])}, types=["hydrometry"]
    )
    state.workspace = SimpleNamespace(root=tmp_path)

    with mock.patch.object(overview_module, "record_source_path", return_value=source):
        entries = overview_module.loaded_inputs(state, tmp_path)

    (entry,) = entries
    assert entry.variable.endswith(":discharge")
    assert entry.provider == "hubeau"
    assert entry.request["station"] == "H1"
    assert entry.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert entry.bytes == source.stat().st_size


def test_record_without_file_is_no_input(tmp_path) -> None:
    record = _points("H1", "2020-01-01", "2020-01-02")
    state = _state({"hydrometry": SimpleNamespace(points=[record], fields=[])}, types=[])
    state.workspace = SimpleNamespace(root=tmp_path)

    with mock.patch.object(overview_module, "record_source_path", return_value=None):
        assert overview_module.loaded_inputs(state, tmp_path) == []


@pytest.mark.parametrize("sources", [[], [SimpleNamespace(source="file")]])
def test_no_network_map_without_source_or_config_path(sources) -> None:
    cfg = SimpleNamespace(data=SimpleNamespace(hydrography=SimpleNamespace(sources=sources)))
    assert hydrography_resolver.resolve_network_map_path(cfg, config_path=None) is None
