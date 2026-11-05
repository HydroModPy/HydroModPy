"""The [site] section: the name grammar and the URI form are refused by name."""

from __future__ import annotations

import inspect
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.calibration.config import (
    CalibOutputPoint,
    CalibPhaseDecl,
    CalibrationConfig,
    MatchingHydrographicNetworkOptions,
)
from hydromodpy.config.metrics_config import MetricsConfig
from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.core.site import GaugeConflictError, SiteConfig, resolve_gauge, site_fingerprint
from hydromodpy.core.site.row import SiteRow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.timeseries_config import TimeseriesSelectionMixin
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_param_sections import normalize_values
from tests._helpers.run_stores import open_run_store


@pytest.mark.parametrize("name", ["nancon", "J0014010", "le_nancon_2", "A_b_9"])
def test_a_site_name_is_letters_digits_and_underscores(name: str) -> None:
    assert SiteConfig(name=name).name == name


@pytest.mark.parametrize("name", ["", "le-nancon", "nancon.v2", "le nancon", "nançon", "a/b"])
def test_a_site_name_with_another_character_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match="name"):
        SiteConfig(name=name)


@pytest.mark.parametrize("uri", ["hubeau:J0014010", "bdtopage:J001-0000", "hubeau:a_b"])
def test_a_registry_uri_is_accepted(uri: str) -> None:
    assert SiteConfig(name="nancon", uri=uri).uri == uri


@pytest.mark.parametrize("uri", ["J0014010", "sandre:J0014010", "hubeau:", "hubeau:J00 14"])
def test_a_uri_outside_the_two_registries_is_refused(uri: str) -> None:
    with pytest.raises(ValidationError, match="uri"):
        SiteConfig(name="nancon", uri=uri)


def test_an_unknown_site_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="station"):
        SiteConfig(name="nancon", station="J0014010")


def test_the_name_is_required() -> None:
    with pytest.raises(ValidationError, match="name"):
        SiteConfig(label="Le Nançon")


SITE = SiteConfig(name="nancon", gauge="J0014010")


def test_an_absent_key_takes_the_gauge() -> None:
    assert resolve_gauge(SITE, None, field="calibration.observed_station_id") == "J0014010"
    assert resolve_gauge(SITE, [], field="data.hydrometry.sources.station_ids") == "J0014010"


def test_the_same_station_is_accepted() -> None:
    assert resolve_gauge(SITE, "J0014010", field="calibration.observed_station_id") == "J0014010"


def test_a_list_holding_the_gauge_is_accepted() -> None:
    declared = ["J0010010", "J0014010"]
    assert resolve_gauge(SITE, declared, field="data.hydrometry.sources.station_ids") == "J0014010"


def test_another_station_is_refused_naming_both_keys() -> None:
    with pytest.raises(GaugeConflictError) as caught:
        resolve_gauge(SITE, "J0010010", field="calibration.observed_station_id")
    message = str(caught.value)
    assert "site.gauge = 'J0014010'" in message
    assert "calibration.observed_station_id = 'J0010010'" in message
    assert isinstance(caught.value, ConfigError)


def test_a_list_without_the_gauge_is_refused() -> None:
    with pytest.raises(GaugeConflictError, match="station_ids"):
        resolve_gauge(SITE, ["J0010010"], field="data.hydrometry.sources.station_ids")


def test_without_a_site_gauge_the_declared_value_stands() -> None:
    bare = SiteConfig(name="nancon")
    assert resolve_gauge(bare, "J0010010", field="metrics.station") == "J0010010"
    assert resolve_gauge(None, ["A", "B"], field="data.hydrometry.sources.station_ids") == "A"
    assert resolve_gauge(None, None, field="metrics.station") is None


NANCON = (389285.910, 6816518.749)


def test_the_same_declaration_gives_the_same_fingerprint() -> None:
    first = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    second = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert first == second
    assert len(first) == 16
    int(first, 16)


def test_the_dem_resolution_does_not_enter_the_fingerprint() -> None:
    # A run at 25 m and one at 75 m declare the same outlet: one site, two areas.
    # The function reads the declaration only, so it has no way to take the DEM.
    assert set(inspect.signature(site_fingerprint).parameters) == {
        "crs",
        "kind",
        "outlet",
        "polygon_sha256",
    }
    with pytest.raises(TypeError):
        site_fingerprint(  # type: ignore[call-arg]
            crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON, dem_resolution=75.0
        )
    at_25_m = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    at_75_m = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert at_25_m == at_75_m


def test_the_outlet_is_rounded_to_the_metre() -> None:
    exact = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    copied = site_fingerprint(
        crs="EPSG:2154", kind="from_outlet_coord", outlet=(389286.2, 6816518.6)
    )
    moved = site_fingerprint(
        crs="EPSG:2154", kind="from_outlet_coord", outlet=(389287.0, 6816518.749)
    )
    assert exact == copied
    assert exact != moved


def test_the_crs_and_the_kind_enter_the_fingerprint() -> None:
    base = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert base != site_fingerprint(crs="EPSG:3857", kind="from_outlet_coord", outlet=NANCON)
    assert base != site_fingerprint(crs="EPSG:2154", kind="dem", outlet=NANCON)


def test_a_polygon_is_named_by_its_digest() -> None:
    digest = "AB" * 32
    upper = site_fingerprint(crs="EPSG:2154", kind="from_polyg_shp", polygon_sha256=digest)
    lower = site_fingerprint(crs="EPSG:2154", kind="from_polyg_shp", polygon_sha256=digest.lower())
    assert upper == lower


def test_a_declaration_without_outlet_or_polygon_is_refused() -> None:
    with pytest.raises(ValueError, match="outlet or a polygon"):
        site_fingerprint(crs="EPSG:2154", kind="dem")


SINGLE_STATIONS = [
    (MetricsConfig, "station"),
    (SiteConfig, "gauge"),
    (CalibOutputPoint, "observes"),
]


def _field(model: type, name: str) -> TypeAdapter:
    return TypeAdapter(model.model_fields[name].rebuild_annotation())


@pytest.mark.parametrize(("model", "name"), SINGLE_STATIONS)
def test_a_toml_key_that_names_a_station_refuses_the_word(model: type, name: str) -> None:
    field = _field(model, name)

    assert field.validate_python("J0014010") == "J0014010"
    assert field.validate_python(None) is None
    with pytest.raises(ValidationError, match="Write the gauge code"):
        field.validate_python("catchment")


def test_a_list_of_stations_refuses_the_word() -> None:
    field = _field(TimeseriesSelectionMixin, "station_ids")

    assert field.validate_python(["J0014010", "domain"]) == ["J0014010", "domain"]
    with pytest.raises(ValidationError, match="cannot name a station"):
        field.validate_python(["J0014010", "catchment"])


def test_a_site_table_refuses_the_word() -> None:
    assert SiteRow(site="nancon", gauge="J0014010").gauge == "J0014010"
    with pytest.raises(ValueError, match="column gauge.*Write the gauge code"):
        SiteRow(site="nancon", gauge="catchment")


def _record(station_id: str) -> PointRecord:
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="custom",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(["2000-01-01"]), "value": [1.0]}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 1),
    )


def test_a_loaded_record_refuses_the_word() -> None:
    assert _record("J0014010").station_id == "J0014010"
    with pytest.raises(DataContractViolation, match="discharge from custom.*gauge code"):
        _record("catchment")


def test_the_store_refuses_a_measurement_under_the_word(tmp_path) -> None:
    series = pd.Series([1.0], index=pd.to_datetime(["2000-02-01"]))
    with open_run_store(tmp_path, "run") as store:
        store.write_timeseries(store.sim_id, "catchment", "discharge", series)
        with pytest.raises(DataContractViolation, match="Observed discharge.*gauge code"):
            store.write_timeseries(
                store.sim_id, "catchment", "discharge", series, source="observed"
            )


@pytest.mark.parametrize("zone", ["core", "domain", None])
def test_the_store_keeps_a_zone_that_is_not_the_word(tmp_path, zone: str | None) -> None:
    with open_run_store(tmp_path, "run") as store:
        store.write_parameters(store.sim_id, [{"param_name": "K", "zone_id": zone, "value": 1.0}])


def test_the_store_refuses_a_zone_under_the_word(tmp_path) -> None:
    with (
        open_run_store(tmp_path, "run") as store,
        pytest.raises(
            DataContractViolation, match="Parameter K.*Write no zone for a uniform value"
        ),
    ):
        store.write_parameters(
            store.sim_id, [{"param_name": "K", "zone_id": "catchment", "value": 1.0}]
        )


def test_a_field_refuses_a_zone_under_the_word() -> None:
    values = {"core": 1e-5, "domain": 3e-4}
    assert normalize_values(values, label="field.values") == values
    field = FieldParam(
        identifier="K",
        kind="heterogeneous",
        unit="m/s",
        values_by_key=values,
        field_spatial_id="catchment_zones",
    )
    assert np.isclose(field.values_by_key["domain"], 3e-4)

    with pytest.raises(ValueError, match="field.values.*cannot name a zone"):
        normalize_values({"catchment": 1e-5}, label="field.values")
    with pytest.raises(ConfigError, match="K.values.*Name the zone after what it holds"):
        FieldParam(
            identifier="K",
            kind="heterogeneous",
            unit="m/s",
            values_by_key={"catchment": 1e-5},
            field_spatial_id="catchment_zones",
        )
