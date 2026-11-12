"""The [site] section: the name grammar and the URI form are refused by name."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_outputs import CalibOutputPoint
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.core.config_kit.field_param.sections import normalize_values
from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.core.site.config import SiteConfig, site_fingerprint
from hydromodpy.core.site.row import SiteRow
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.timeseries_config import TimeseriesSelectionMixin
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.results.metric_rule import MetricsConfig
from tests._helpers.run_stores import open_run_store

SITE = SiteConfig(name="nancon", gauge="J0014010")


NANCON = (389285.910, 6816518.749)


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
        source="file",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": pd.to_datetime(["2000-01-01"]), "value": [1.0]}),
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2000, 1, 1),
    )


def test_a_loaded_record_refuses_the_word() -> None:
    assert _record("J0014010").station_id == "J0014010"
    with pytest.raises(DataContractViolation, match="discharge from file.*gauge code"):
        _record("catchment")


def test_the_store_refuses_a_measurement_under_the_word(tmp_path) -> None:
    series = pd.Series([1.0], index=pd.to_datetime(["2000-02-01"]))
    with open_run_store(tmp_path, "run") as store:
        store.write_timeseries(store.sim_id, "catchment", "discharge", series)
        with pytest.raises(DataContractViolation, match="Observed discharge.*gauge code"):
            store.write_timeseries(
                store.sim_id, "catchment", "discharge", series, source="observed"
            )


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
