"""Conformance suite for the data-source port, run against every source.

What a source declares and what it refuses before reaching its provider runs on every
source the registry serves -- a source of any section, an installed one too. Run this
file from a clone with the plugin installed (``tests/ports/test_data_source.py``
proves it). What reaches the provider needs a :class:`SourceCase`, which says which
function a source delegates to.

The port is only worth its name if adapters that agree on nothing else answer
the same questions the same way. The river networks this build ships agree on
too much, so three doubles defined here stand for the plugin sources an
``installed`` request may name:

============== ============ ============= ========= ==============
source         payload kind extent CRS    period    writes out_dir
============== ============ ============= ========= ==============
bdtopage       ``features`` **EPSG:2154** refused   no
double-gauge   ``points``   EPSG:4326     required  no
double-grid    ``fields``   **EPSG:2154** required  no
double-tiles   ``files``    **EPSG:2154** refused   **yes**
============== ============ ============= ========= ==============

Two CRS, all four payload kinds, all three values of ``PeriodNeed`` and both answers
on writing. A member that only makes sense for one of them cannot survive this
file, and :func:`test_the_suite_spans_the_vocabularies` fails if a future edit
collapses that spread.

Two layers, and why both are needed
-----------------------------------
**Layer A** records the provider entry point each adapter delegates to and
reads the arguments off it. It is uniform over every case the suite names and it
is where the declarations are compared against a real call. A source that reached
the network behind its own provider function would be caught by
the ``no_network`` fixture, which makes every transport of this tree raise.

**Layer B** lets the real adapter run all the way to the wire with only the
HTTP transport stubbed, and reads the bounding box out of the query string that
was about to be sent. Layer A alone would prove the adapter passes *something*
to a function; Layer B proves the reprojected coordinates are what the provider
receives. It covers the three shipped river networks, which all go through
``hydromodpy.core.io.fetch.HTTPClient.request``.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any, ClassVar

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.core.exceptions import (
    DataCapabilityError,
    DataProductError,
    DataRequestError,
)
from hydromodpy.data.common.clients.explore2_files import (
    Explore2Etp,
    Explore2Precipitation,
)
from hydromodpy.data.common.clients.sim2_products import (
    Sim2Etp,
    Sim2Humidity,
    Sim2Precipitation,
    Sim2Radiation,
    Sim2Recharge,
    Sim2Runoff,
    Sim2SoilMoisture,
    Sim2Temperature,
    Sim2Wind,
)
from hydromodpy.data.source import registry
from hydromodpy.data.source.port import (
    ALL_PAYLOAD_KINDS,
    ALL_PERIOD_NEEDS,
    ALL_SELECTORS,
    SOURCE_MEMBERS,
    DataSource,
    Extent,
    FetchRequest,
    FetchResult,
    Period,
    extent_for,
    missing_source_members,
    require_declared_variables,
    require_period,
    require_selectors,
)
from hydromodpy.data.variables.crossings.apis.bdtopo import BdTopoCrossings
from hydromodpy.data.variables.crossings.apis.roe import RoeCrossings
from hydromodpy.data.variables.dem.apis.ign_dem_fr import IgnGeoplateformeDem
from hydromodpy.data.variables.geology.apis.brgm_1m import Brgm1m
from hydromodpy.data.variables.geology.apis.brgm_50k import Brgm50k
from hydromodpy.data.variables.hydrography.apis.bdtopage import BdTopageSource
from hydromodpy.data.variables.hydrography.apis.euhydro import EuHydroSource
from hydromodpy.data.variables.hydrography.apis.osm import OsmSource
from hydromodpy.data.variables.hydrometry.apis.hubeau import HubeauHydrometry
from hydromodpy.data.variables.intermittency.apis.hubeau import HubeauIntermittency
from hydromodpy.data.variables.oceanic.apis.shom import ShomSeaLevel
from hydromodpy.data.variables.oceanic.constant import ConstantSeaLevel
from hydromodpy.data.variables.piezometry.apis.hubeau import HubeauPiezometry
from hydromodpy.data.variables.recharge.synthetic import SyntheticRecharge
from hydromodpy.data.variables.water_quality.apis.hubeau import HubeauWaterQuality

from ._installed_probe import run_suite, unpack

pyproj = pytest.importorskip("pyproj")

# A basin-sized box over eastern Brittany, in the CRS no source of this suite
# declares: every adapter has to convert it, one of them by 300 kilometers.
CALLER_EXTENT = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
CALLER_EXTENT_L93 = Extent(
    xmin=317000.0, ymin=6780000.0, xmax=354000.0, ymax=6826000.0, crs="EPSG:2154"
)
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 3, 31))


def _expected_bbox(extent: Extent, crs: str) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    source = pyproj.CRS.from_user_input(extent.crs)
    target = pyproj.CRS.from_user_input(crs)
    if source.equals(target):
        return extent.bbox
    transformer = pyproj.Transformer.from_crs(source, target, always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# The sources under test, and where each one delegates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceCase:
    """One source, plus how to intercept the provider call it makes."""

    section: str
    name: str
    build: Callable[[], Any]
    provider_module: str
    provider_attr: str
    read_bbox: Callable[[tuple, dict], tuple | None]
    canned: Callable[[], Any]

    @property
    def key(self) -> str:
        """The id the registry knows this source under."""
        return f"{self.section}_{self.name}"

    def request(self, out_dir: Path, *, extent: Extent | None = CALLER_EXTENT) -> FetchRequest:
        """A request this source accepts, with the period it needs and no other."""
        source = self.build()
        period = PERIOD if source.period_need in ("required", "optional") else None
        effective_extent = None if not source.selectors else extent
        return FetchRequest(out_dir=out_dir, extent=effective_extent, period=period)


def _empty_frame() -> Any:
    import geopandas as gpd

    return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def _gauge_provider(*, bbox, station_ids, start, end) -> list:
    """Stands for a station provider's ``fetch``; the suite replaces it."""
    return []


def _grid_provider(*, bbox, start, end) -> list:
    """Stands for a grid provider's download; the suite replaces it."""
    return []


def _tiles_canned() -> Path:
    """A real one-pixel GeoTIFF the provider stands for, written in the sandbox."""
    import tempfile

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    handle = tempfile.NamedTemporaryFile(  # type: ignore[arg-type]
        prefix="hmp_tiles_wire_", suffix=".tif", delete=False
    )
    handle.close()
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(340000.0, 6810000.0, 5.0, 5.0),
        "nodata": -9999.0,
    }
    with rasterio.open(handle.name, "w", **profile) as dst:
        dst.write(np.full((1, 1), 17.0, dtype="float32"), 1)
    return Path(handle.name)


def _tile_provider(*, output_dir, bbox) -> Path:
    """Stands for a tile downloader that writes under the directory it is given."""
    return Path(output_dir) / "tiles.tif"


def _dem_canned() -> Path:
    """A one-pixel Lambert-93 GeoTIFF carrying a nodata the header declares."""
    import tempfile

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    handle = tempfile.NamedTemporaryFile(  # type: ignore[arg-type]
        prefix="hmp_dem_wire_", suffix=".tif", delete=False
    )
    handle.close()
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(340000.0, 6810000.0, 5.0, 5.0),
        "nodata": -9999.0,
    }
    with rasterio.open(handle.name, "w", **profile) as dst:
        dst.write(np.full((1, 1), 17.0, dtype="float32"), 1)
    return Path(handle.name)


def _vector_canned() -> Path:
    """A small file a vector source hands back; only its bytes matter here."""
    import tempfile

    handle = tempfile.NamedTemporaryFile(  # type: ignore[arg-type]
        prefix="hmp_vector_wire_", suffix=".gpkg", delete=False
    )
    handle.write(b"crossings contract canned payload")
    handle.close()
    return Path(handle.name)


def _crossings_page_canned() -> Any:
    """One page of crossings records, in the fixed columns of the variable."""
    from shapely.geometry import LineString

    from hydromodpy.data.variables.crossings import records

    return [
        records.build(
            [LineString([(340000.0, 6800000.0), (340100.0, 6800100.0)])],
            kind=["road"],
            source="",
            name=[""],
            drop_m=[float("nan")],
            crs="EPSG:2154",
        )
    ]


def _point_record_canned(variable: str, unit: str, source: str) -> list:
    import pandas as pd

    from hydromodpy.data.contracts.timeseries import PointRecord

    df = pd.DataFrame(
        {
            "datetime": [datetime(2020, 1, 1), datetime(2020, 1, 2)],
            "value": [1.0, 1.0],
        }
    )
    return [
        PointRecord(
            station_id="ST01" if source == "shom" else source,
            variable=variable,
            source=source,
            unit=unit,
            frequency="D" if source != "shom" else "H",
            data=df,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 3, 31),
        )
    ]


def _field_record_canned(variable: str, unit: str, source: str = "sim2") -> list:
    import numpy as np
    import xarray as xr

    from hydromodpy.data.contracts.spatial_field import FieldRecord

    da = xr.DataArray(
        np.zeros((1, 1, 1), dtype="float32"),
        dims=("time", "y", "x"),
        coords={
            "time": [datetime(2020, 1, 1)],
            "y": [6800000.0],
            "x": [340000.0],
        },
    )
    return [
        FieldRecord(
            variable=variable,
            source=source,
            unit=unit,
            data=da.to_dataset(name=variable),
            bbox=(335000.0, 6795000.0, 345000.0, 6805000.0),
            crs="EPSG:2154",
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 3, 31),
            frequency="D",
        )
    ]


def _sim2_precipitation_canned() -> list:
    return [
        *_field_record_canned("precipitation_liquid", "mm/day", "sim2"),
        *_field_record_canned("precipitation_solid", "mm/day", "sim2"),
        *_field_record_canned("precipitation_total", "mm/day", "sim2"),
    ]


def _sim2_radiation_canned() -> list:
    return [
        *_field_record_canned("radiation_atmospheric", "MJ/m2/j", "sim2"),
        *_field_record_canned("radiation_visible", "MJ/m2/j", "sim2"),
    ]


def _provider(name: str) -> Callable[..., Any]:
    """Look the provider up at call time, so the recorder that replaced it is used."""
    return getattr(sys.modules[__name__], name)


class _GaugeDouble:
    """A station source: points, WGS84, a period required, two selectors."""

    source_id = "double-gauge"
    section: ClassVar[str] = "conformance-doubles"
    payload_kind = "points"
    extent_crs = "EPSG:4326"
    selectors = ("extent", "station_ids")
    period_need = "required"
    hosts = ("gauge.example",)
    writes_out_dir = False

    def __init__(self) -> None:
        self.variables = ("gauge_level",)

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request) if request.extent is not None else None
        records = _provider("_gauge_provider")(
            bbox=None if extent is None else extent.bbox,
            station_ids=list(request.station_ids) or None,
            start=period.start,
            end=period.end,
        )
        require_declared_variables(self, [record.variable for record in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            points=tuple(records),
        )


class _GridDouble:
    """A grid source: fields, Lambert-93, a period required."""

    source_id = "double-grid"
    section: ClassVar[str] = "conformance-doubles"
    payload_kind = "fields"
    extent_crs = "EPSG:2154"
    selectors = ("extent",)
    period_need = "required"
    hosts = ("grid.example",)
    writes_out_dir = False

    def __init__(self) -> None:
        self.variables = ("grid_total",)

    def fetch(self, request: FetchRequest) -> FetchResult:
        require_selectors(self, request)
        period = require_period(self, request)
        extent = extent_for(self, request)
        records = _provider("_grid_provider")(bbox=extent.bbox, start=period.start, end=period.end)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            fields=tuple(records),
        )


class _TileDouble:
    """A tile source: files, Lambert-93, no time axis, writes under ``out_dir``."""

    source_id = "double-tiles"
    section: ClassVar[str] = "conformance-doubles"
    payload_kind = "files"
    extent_crs = "EPSG:2154"
    selectors = ("extent",)
    period_need = "refused"
    hosts = ("tiles.example",)
    writes_out_dir = True

    def __init__(self) -> None:
        self.variables = ("elevation",)

    def fetch(self, request: FetchRequest) -> FetchResult:
        from hydromodpy.data.contracts.file_record import FileRecord

        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        merged = _provider("_tile_provider")(output_dir=request.out_dir, bbox=extent.bbox)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(FileRecord.of(merged, state="raw", nodata=None, origin=self.hosts[0]),),
        )


BUILTIN_CASES: tuple[SourceCase, ...] = (
    SourceCase(
        section="hydrography",
        name="bdtopage",
        build=BdTopageSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.bdtopage",
        provider_attr="fetch_projected",
        read_bbox=lambda args, kwargs: args[0] if args else kwargs.get("bbox"),
        canned=_empty_frame,
    ),
    SourceCase(
        section="hydrography",
        name="osm",
        build=OsmSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.osm",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: args[1] if len(args) > 1 else kwargs.get("bbox_wgs84"),
        canned=_empty_frame,
    ),
    SourceCase(
        section="hydrography",
        name="euhydro",
        build=EuHydroSource,
        provider_module="hydromodpy.data.variables.hydrography.apis.euhydro",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: args[1] if len(args) > 1 else kwargs.get("bbox_wgs84"),
        canned=_empty_frame,
    ),
    SourceCase(
        section="dem",
        name="ign_geoplateforme_dem",
        build=IgnGeoplateformeDem,
        provider_module="hydromodpy.data.variables.dem.apis.ign_dem_fr",
        provider_attr="fetch_ign_dem",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_dem_canned,
    ),
    SourceCase(
        section="geology",
        name="brgm_1m",
        build=Brgm1m,
        provider_module="hydromodpy.data.variables.geology.apis.brgm_1m",
        provider_attr="fetch_brgm_1m",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_vector_canned,
    ),
    SourceCase(
        section="geology",
        name="brgm_50k",
        build=Brgm50k,
        provider_module="hydromodpy.data.variables.geology.apis.brgm_50k",
        provider_attr="fetch_brgm_50k",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_vector_canned,
    ),
    SourceCase(
        section="crossings",
        name="bdtopo",
        build=BdTopoCrossings,
        provider_module="hydromodpy.data.variables.crossings.apis.bdtopo",
        provider_attr="fetch_pages",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_crossings_page_canned,
    ),
    SourceCase(
        section="crossings",
        name="roe",
        build=RoeCrossings,
        provider_module="hydromodpy.data.variables.crossings.apis.roe",
        provider_attr="fetch_pages",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_crossings_page_canned,
    ),
    SourceCase(
        section="hydrometry",
        name="hubeau",
        build=HubeauHydrometry,
        provider_module="hydromodpy.data.variables.hydrometry.apis.hubeau",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _point_record_canned("discharge", "m3/s", "hubeau"),
    ),
    SourceCase(
        section="piezometry",
        name="hubeau",
        build=HubeauPiezometry,
        provider_module="hydromodpy.data.variables.piezometry.apis.hubeau",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _point_record_canned("groundwater_level", "m", "hubeau"),
    ),
    SourceCase(
        section="water_quality",
        name="hubeau",
        build=lambda: HubeauWaterQuality(parameters=["pH"]),
        provider_module="hydromodpy.data.variables.water_quality.apis.hubeau",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _point_record_canned("pH", "u", "hubeau"),
    ),
    SourceCase(
        section="intermittency",
        name="hubeau",
        build=HubeauIntermittency,
        provider_module="hydromodpy.data.variables.intermittency.apis.hubeau",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _point_record_canned("flow_state", "code", "hubeau"),
    ),
    SourceCase(
        section="precipitation",
        name="sim2",
        build=Sim2Precipitation,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_sim2_precipitation_canned,
    ),
    SourceCase(
        section="etp",
        name="sim2",
        build=Sim2Etp,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("etp", "mm/day", "sim2"),
    ),
    SourceCase(
        section="temperature",
        name="sim2",
        build=Sim2Temperature,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("temperature", "degC", "sim2"),
    ),
    SourceCase(
        section="wind",
        name="sim2",
        build=Sim2Wind,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("wind", "m/s", "sim2"),
    ),
    SourceCase(
        section="humidity",
        name="sim2",
        build=Sim2Humidity,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("humidity", "%", "sim2"),
    ),
    SourceCase(
        section="radiation",
        name="sim2",
        build=Sim2Radiation,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_sim2_radiation_canned,
    ),
    SourceCase(
        section="soil_moisture",
        name="sim2",
        build=Sim2SoilMoisture,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("soil_moisture_index", "%", "sim2"),
    ),
    SourceCase(
        section="runoff",
        name="sim2",
        build=Sim2Runoff,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("runoff", "mm/day", "sim2"),
    ),
    SourceCase(
        section="recharge",
        name="sim2",
        build=Sim2Recharge,
        provider_module="hydromodpy.data.common.clients.sim2_products",
        provider_attr="fetch_sim2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("recharge", "mm/day", "sim2"),
    ),
    SourceCase(
        section="precipitation",
        name="explore2",
        build=lambda: Explore2Precipitation(path=Path("explore2_precipitation_stub.nc")),
        provider_module="hydromodpy.data.common.clients.explore2_files",
        provider_attr="read_explore2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("precipitation", "mm/day", "explore2"),
    ),
    SourceCase(
        section="etp",
        name="explore2",
        build=lambda: Explore2Etp(path=Path("explore2_etp_stub.nc")),
        provider_module="hydromodpy.data.common.clients.explore2_files",
        provider_attr="read_explore2",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _field_record_canned("etp", "mm/day", "explore2"),
    ),
    SourceCase(
        section="recharge",
        name="synthetic",
        build=SyntheticRecharge,
        provider_module="hydromodpy.data.variables.recharge.synthetic",
        provider_attr="generate",
        read_bbox=lambda args, kwargs: None,
        canned=lambda: _point_record_canned("recharge", "mm/day", "synthetic"),
    ),
    SourceCase(
        section="oceanic",
        name="constant",
        build=ConstantSeaLevel,
        provider_module="hydromodpy.data.variables.oceanic.constant",
        provider_attr="generate_constant",
        read_bbox=lambda args, kwargs: None,
        canned=lambda: _point_record_canned("mean_sea_level", "m", "constant"),
    ),
    SourceCase(
        section="oceanic",
        name="shom",
        build=ShomSeaLevel,
        provider_module="hydromodpy.data.variables.oceanic.apis.shom",
        provider_attr="fetch",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=lambda: _point_record_canned("sea_level", "m", "shom"),
    ),
)

DOUBLE_CASES: tuple[SourceCase, ...] = (
    SourceCase(
        section="conformance-doubles",
        name="double-gauge",
        build=_GaugeDouble,
        provider_module=__name__,
        provider_attr="_gauge_provider",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=list,
    ),
    SourceCase(
        section="conformance-doubles",
        name="double-grid",
        build=_GridDouble,
        provider_module=__name__,
        provider_attr="_grid_provider",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=list,
    ),
    SourceCase(
        section="conformance-doubles",
        name="double-tiles",
        build=_TileDouble,
        provider_module=__name__,
        provider_attr="_tile_provider",
        read_bbox=lambda args, kwargs: kwargs.get("bbox"),
        canned=_tiles_canned,
    ),
)


def _user_source_cases() -> tuple[SourceCase, ...]:
    """One case per ``<section>_file`` and ``<section>_url`` key the registry ships.

    The two user sources call no provider with a box, so the cases of layer A
    do not apply to them. They are generated from the registry, so a section
    that gains a user source is covered without a line written here, and
    :func:`test_a_user_source_serves_its_one_file` checks what they return.
    """
    cases = []
    for key in sorted(registry.data_sources.names(shipped_only=True)):
        section, _, name = key.rpartition("_")
        if name not in ("file", "url"):
            continue
        cases.append(
            SourceCase(
                section=section,
                name=name,
                build=lambda key=key: registry.data_sources.get(key)(),
                provider_module="hydromodpy.data.source.url" if name == "url" else "",
                provider_attr="download" if name == "url" else "",
                read_bbox=lambda args, kwargs: None,
                canned=lambda: None,
            )
        )
    return tuple(cases)


USER_CASES = _user_source_cases()
USER_PARAMS = [pytest.param(case, id=case.key) for case in USER_CASES]

CASES = BUILTIN_CASES + DOUBLE_CASES
CASE_PARAMS = [pytest.param(case, id=case.key) for case in CASES]
_CASES_BY_NAME = {case.name: case for case in CASES}

# Every source the registry serves, shipped or installed, and the doubles. A
# source with a constructor that needs an argument has to give it a default for
# this suite. The registry is resolved at run time, inside each test: a key
# whose class is not in the tree yet fails as one named red case, and does not
# take the collection of the others down with it.
BUILTIN_PARAMS = [
    *(pytest.param("registry", key, id=key) for key in registry.data_sources.names()),
    *(pytest.param("double", case.name, id=case.name) for case in DOUBLE_CASES),
]


def _resolve(kind: str, name: str) -> Any:
    """Build one source the parametrization named."""
    if kind == "registry":
        return registry.data_sources.get(name)()
    return _CASES_BY_NAME[name].build()


@dataclass
class ProviderCall:
    """What the adapter handed its provider."""

    args: tuple
    kwargs: dict


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every HTTP transport of this tree raise.

    Anti-vacuity for layer A: an adapter that ignored its provider function and
    reached out on its own would be indistinguishable from one that behaved,
    because the provider stub would record nothing either way.
    """
    import requests

    from hydromodpy.core.io.fetch import HTTPClient

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a source reached the network outside its provider function")

    monkeypatch.setattr(HTTPClient, "request", _refuse)
    monkeypatch.setattr(requests.Session, "request", _refuse)


@pytest.fixture
def record_provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[SourceCase], list[ProviderCall]]:
    """Replace a case's provider entry point with a recorder."""

    def install(case: SourceCase, *, result: Any | None = None) -> list[ProviderCall]:
        import importlib

        module = importlib.import_module(case.provider_module)
        calls: list[ProviderCall] = []
        payload = case.canned() if result is None else result

        def _record(*args: object, **kwargs: object) -> Any:
            calls.append(ProviderCall(args=args, kwargs=kwargs))
            return payload

        monkeypatch.setattr(module, case.provider_attr, _record)
        return calls

    return install


# --------------------------------------------------------------------------- #
# Anti-vacuity
# --------------------------------------------------------------------------- #


def test_the_suite_covers_every_source_this_build_ships() -> None:
    """An adapter added to the registry and not here would be untested by omission.

    The cases name their section and their id, joined the way the registry keys
    them, so a source can only be missing from this suite by being missing from
    the registry too.
    """
    assert {case.key for case in BUILTIN_CASES + USER_CASES} == set(
        registry.data_sources.names(shipped_only=True)
    )


@pytest.mark.parametrize("case", USER_PARAMS)
def test_a_user_source_serves_its_one_file(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``file`` source reads in place, a ``url`` source fills ``out_dir`` once."""
    import hashlib

    from hydromodpy.core.io.fetch import Fetched
    from hydromodpy.data.contracts.file_record import FileRecord

    source = case.build()
    assert source.source_id == case.name
    assert source.selectors == ()
    out_dir = tmp_path / "out"
    if case.name == "file":
        given = tmp_path / "given.bin"
        given.write_bytes(b"user file")
        source.path = given
    else:
        source.url = "https://example.org/given.bin"
        calls: list[str] = []

        def _download(url: str, dest: Path, **_kwargs: object) -> Fetched:
            calls.append(url)
            Path(dest).write_bytes(b"user file")
            digest = hashlib.sha256(b"user file").hexdigest()
            return Fetched(path=Path(dest), sha256=digest, size=9, final_url=url)

        monkeypatch.setattr(f"{case.provider_module}.{case.provider_attr}", _download)
    period = PERIOD if source.period_need in ("required", "optional") else None
    result = source.fetch(FetchRequest(out_dir=out_dir, period=period))

    assert result.source_id == source.source_id
    assert result.kind == source.payload_kind
    assert result.variables == source.variables == (case.section,)
    assert len(result.files) == 1 and isinstance(result.files[0], FileRecord)
    written = out_dir.exists() and any(out_dir.iterdir())
    assert written is source.writes_out_dir
    if case.name == "url":
        assert calls == ["https://example.org/given.bin"]
        assert result.files[0].path.parent == out_dir


def test_the_suite_spans_the_vocabularies() -> None:
    """A suite of three lookalikes would pass every assertion below for free."""
    sources = [case.build() for case in CASES]
    assert {s.payload_kind for s in sources} == set(ALL_PAYLOAD_KINDS)
    assert len({s.extent_crs for s in sources}) >= 2
    assert {s.period_need for s in sources} == set(ALL_PERIOD_NEEDS)
    assert len({s.writes_out_dir for s in sources}) == 2
    assert {s.source_id for s in sources} == {case.name for case in CASES}
    assert {s.section for s in sources} == {case.section for case in CASES}


# --------------------------------------------------------------------------- #
# What a source declares
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_a_source_has_every_member_the_port_asks_for(kind: str, name: str) -> None:
    source = _resolve(kind, name)
    assert missing_source_members(source) == ()
    assert isinstance(source, DataSource)
    assert set(SOURCE_MEMBERS) <= set(dir(source))


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_the_declarations_use_the_closed_vocabularies(kind: str, name: str) -> None:
    source = _resolve(kind, name)
    assert source.payload_kind in ALL_PAYLOAD_KINDS
    assert source.period_need in ALL_PERIOD_NEEDS
    assert set(source.selectors) <= set(ALL_SELECTORS), (
        "a source may select by nothing, and then only by nothing"
    )
    assert len(set(source.selectors)) == len(source.selectors)
    assert source.variables, "a source that names no variable serves nothing askable"
    assert isinstance(source.writes_out_dir, bool)


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_the_declared_extent_crs_resolves(kind: str, name: str) -> None:
    """A CRS nothing can resolve makes every conversion into this source fail."""
    source = _resolve(kind, name)
    assert pyproj.CRS.from_user_input(source.extent_crs) is not None


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_the_declared_hosts_are_bare_names(kind: str, name: str) -> None:
    """A host list is what a capability publishes; a URL there would not compare.

    A source computed from the section alone declares no host, and that empty
    list is the honest answer: nothing to contact, nothing to publish.
    """
    source = _resolve(kind, name)
    assert isinstance(source.hosts, tuple)
    for host in source.hosts:
        assert host == host.strip().lower()
        assert "/" not in host and ":" not in host
        assert not host.startswith("http")


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_a_shipped_source_reads_its_hosts_in_the_licence_table(kind: str, name: str) -> None:
    """The one table the licence pages read is the one a shipped source answers.

    A plugin source writes its own hosts, so the suite checks only what this
    build ships, and the section is the marker: a source of no shipped section
    is somebody else's.
    """
    if kind != "registry" or name not in registry.data_sources.builtin_paths:
        pytest.skip("only a source this build ships reads the licence table")
    from hydromodpy.schema.sources import source_entry

    source_cls = registry.data_sources.get(name)
    entry = source_entry(getattr(source_cls, "source_id", None))
    if entry is None:
        pytest.skip(f"{name} serves a section the licence pages do not describe")
    assert source_cls().hosts == tuple(entry.hosts), (
        "a shipped source reads its hosts on the licence table, and nothing else"
    )


# --------------------------------------------------------------------------- #
# What a source refuses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_answers_every_selector_it_declares(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    calls = record_provider(case)
    period = PERIOD if source.period_need in ("required", "optional") else None
    if not source.selectors:
        # A source that selects by nothing is asked exactly nothing, and answers.
        request = FetchRequest(out_dir=tmp_path, period=period)
        source.fetch(request)
        assert len(calls) == 1, f"{source.source_id} did not serve the empty request"
        return
    for selector in source.selectors:
        calls.clear()
        if selector == "extent":
            request = FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT, period=period)
        else:
            request = FetchRequest(out_dir=tmp_path, station_ids=("BSS000XXXX",), period=period)
        source.fetch(request)
        assert len(calls) == 1, f"{source.source_id} did not serve selector {selector!r}"


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_a_source_refuses_a_selector_it_does_not_declare(
    kind: str, name: str, tmp_path: Path, no_network: None
) -> None:
    source = _resolve(kind, name)
    undeclared = [sel for sel in ALL_SELECTORS if sel not in source.selectors]
    if not undeclared:
        pytest.skip(f"{source.source_id} declares every selector the port knows")
    period = PERIOD if source.period_need in ("required", "optional") else None
    request = FetchRequest(out_dir=tmp_path, station_ids=("X1",), period=period)
    with pytest.raises(DataCapabilityError) as excinfo:
        source.fetch(request)
    assert "station_ids" in str(excinfo.value)


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_a_source_that_selects_refuses_a_request_that_selects_nothing(
    kind: str, name: str, tmp_path: Path, no_network: None
) -> None:
    """The empty request is a source's to answer, and only a source that selects nothing."""
    source = _resolve(kind, name)
    if not source.selectors:
        pytest.skip(f"{source.source_id} declares selectors = ()")
    with pytest.raises(DataRequestError, match="selects nothing"):
        source.fetch(FetchRequest(out_dir=tmp_path))


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_no_source_answers_two_selectors_at_once(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """The silent one: the station list wins and the extent is dropped.

    Measured in ``piezometry/apis/hubeau.py``: ``if station_ids: ... elif
    bbox:``. A caller that passed both would get exactly what it would have got
    by passing the ids alone, and nothing in the result would say the box was
    ignored. Refused for every source until a provider can intersect them.
    """
    source = case.build()
    if set(source.selectors) != set(ALL_SELECTORS):
        pytest.skip(f"{source.source_id} declares only {list(source.selectors)}")
    calls = record_provider(case)
    period = PERIOD if source.period_need in ("required", "optional") else None
    request = FetchRequest(
        out_dir=tmp_path,
        extent=CALLER_EXTENT,
        station_ids=("BSS000XXXX",),
        period=period,
    )
    with pytest.raises(DataCapabilityError, match="at once"):
        source.fetch(request)
    assert calls == [], "the provider was reached before the request was refused"


@pytest.mark.parametrize(["kind", "name"], BUILTIN_PARAMS)
def test_a_source_answers_the_period_exactly_as_it_declares(
    kind: str, name: str, tmp_path: Path, no_network: None
) -> None:
    source = _resolve(kind, name)
    extent = CALLER_EXTENT if "extent" in source.selectors else None
    if source.period_need == "refused":
        request = FetchRequest(out_dir=tmp_path, extent=extent, period=PERIOD)
        with pytest.raises(DataCapabilityError) as excinfo:
            source.fetch(request)
        assert source.source_id in str(excinfo.value)
    elif source.period_need == "required":
        request = FetchRequest(out_dir=tmp_path, extent=extent, period=None)
        with pytest.raises(DataRequestError) as excinfo:
            source.fetch(request)
        assert source.source_id in str(excinfo.value)
    elif source.period_need == "optional":
        assert (
            require_period(source, FetchRequest(out_dir=tmp_path, extent=extent, period=PERIOD))
            == PERIOD
        )
        assert (
            require_period(source, FetchRequest(out_dir=tmp_path, extent=extent, period=None))
            is None
        )


# --------------------------------------------------------------------------- #
# Layer A: what reaches the provider
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_foreign_crs_extent_reaches_the_provider_in_the_declared_one(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """The claim the whole port exists for, checked against pyproj, not itself."""
    source = case.build()
    if "extent" not in source.selectors:
        pytest.skip(f"{source.source_id} cannot be asked for an extent")
    calls = record_provider(case)
    source.fetch(case.request(tmp_path))
    assert len(calls) == 1
    served = case.read_bbox(calls[0].args, calls[0].kwargs)
    assert served is not None, "the adapter handed its provider no bounding box"
    expected = _expected_bbox(CALLER_EXTENT, source.extent_crs)
    assert tuple(served) == pytest.approx(expected, rel=0, abs=1e-6)


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_an_extent_already_in_the_declared_crs_is_passed_through_untouched(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """No round trip through a transformer when there is nothing to convert."""
    source = case.build()
    if "extent" not in source.selectors:
        pytest.skip(f"{source.source_id} cannot be asked for an extent")
    native = Extent(
        xmin=CALLER_EXTENT_L93.xmin if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.xmin,
        ymin=CALLER_EXTENT_L93.ymin if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.ymin,
        xmax=CALLER_EXTENT_L93.xmax if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.xmax,
        ymax=CALLER_EXTENT_L93.ymax if source.extent_crs == "EPSG:2154" else CALLER_EXTENT.ymax,
        crs=source.extent_crs,
    )
    calls = record_provider(case)
    result = source.fetch(case.request(tmp_path, extent=native))
    served = case.read_bbox(calls[0].args, calls[0].kwargs)
    assert tuple(served) == native.bbox

    spelled_differently = Extent(
        xmin=native.xmin,
        ymin=native.ymin,
        xmax=native.xmax,
        ymax=native.ymax,
        crs=source.extent_crs.lower(),
    )
    calls = record_provider(case)
    other = source.fetch(case.request(tmp_path, extent=spelled_differently))
    assert tuple(case.read_bbox(calls[0].args, calls[0].kwargs)) == native.bbox
    assert other.extent is not None and other.extent.crs == source.extent_crs, (
        "a result reports the CRS the source declares, not the spelling it was handed"
    )
    assert result.extent == other.extent


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_result_says_what_the_source_declared(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    record_provider(case)
    result = source.fetch(case.request(tmp_path))
    assert isinstance(result, FetchResult)
    assert result.source_id == source.source_id
    assert result.kind == source.payload_kind
    assert result.variables == source.variables, (
        "a result names exactly the variables the source it came from declares"
    )
    if result.kind == "files":
        from hydromodpy.data.contracts.file_record import FileRecord

        assert all(isinstance(record, FileRecord) for record in result.files)
    if "extent" in source.selectors:
        assert result.extent is not None
        assert result.extent.crs == source.extent_crs, (
            "the result must report the extent that was queried, not the one that was asked"
        )
    if source.period_need == "refused":
        assert result.period is None
    else:
        assert result.period == PERIOD


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_the_out_dir_reaches_the_provider_only_when_the_source_writes(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    """A source that declares no write never names the directory nor writes in it.

    A writing source reaches the directory one of two ways: it hands ``out_dir``
    to its provider (the tile downloaders take it as ``output_dir``), or it
    stages its files inside it (the crossings sources write between the pages).
    What the suite reads is the directory: a file lands there if and only if the
    source declares ``writes_out_dir``.
    """
    source = case.build()
    calls = record_provider(case)
    request = case.request(tmp_path)
    source.fetch(request)
    reached = tmp_path.exists() and any(tmp_path.iterdir())
    passed = [*calls[0].args, *calls[0].kwargs.values()]
    mentions_out_dir = any(
        isinstance(value, (str, Path)) and Path(value) == request.out_dir for value in passed
    )
    assert (reached or mentions_out_dir) is source.writes_out_dir


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_a_source_that_declares_no_write_leaves_the_out_dir_alone(
    case: SourceCase,
    tmp_path: Path,
    no_network: None,
    record_provider: Callable[..., list[ProviderCall]],
) -> None:
    source = case.build()
    if source.writes_out_dir:
        pytest.skip(f"{source.source_id} declares that it writes under out_dir")
    out_dir = tmp_path / "jobdir"
    out_dir.mkdir()
    record_provider(case)
    source.fetch(case.request(out_dir))
    assert list(out_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# Layer B: what reaches the wire
# --------------------------------------------------------------------------- #


class _CannedResponse:
    """The little of ``requests.Response`` the two adapters of layer B read."""

    def __init__(self, *, content: bytes = b"", payload: object | None = None) -> None:
        self.content = content
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def close(self) -> None:
        return None


@dataclass
class Wire:
    """Every request the stubbed transport was handed, and what to answer with."""

    calls: list[dict]
    responses: list[_CannedResponse]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Iterator[Wire]:
    """Stub the shared HTTP transport and record every request it was given."""
    from hydromodpy.core.io.fetch import HTTPClient

    recorded = Wire(calls=[], responses=[])

    def _request(_self: object, method: str, url: str, **kwargs: Any) -> _CannedResponse:
        recorded.calls.append({"method": method, "url": url, "params": kwargs.get("params") or {}})
        if recorded.responses:
            return recorded.responses.pop(0)
        return _CannedResponse(payload={"data": []})

    monkeypatch.setattr(HTTPClient, "request", _request)
    yield recorded


def test_the_bbox_on_the_bdtopage_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real WFS paging code runs; only the transport is canned."""
    wire.responses.append(
        _CannedResponse(
            content=(
                b'<?xml version="1.0"?><wfs:FeatureCollection numberMatched="0" '
                b'xmlns:wfs="http://www.opengis.net/wfs/2.0"/>'
            )
        )
    )
    source = BdTopageSource()
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT))

    assert [call["url"] for call in wire.calls] == [
        "https://services.sandre.eaufrance.fr/geo/sandre"
    ], "a host outside the declaration was contacted"
    params = wire.calls[0]["params"]
    xmin, ymin, xmax, ymax, urn = params["BBOX"].split(",")
    expected = _expected_bbox(CALLER_EXTENT, source.extent_crs)
    assert urn == "urn:ogc:def:crs:EPSG::2154"
    assert params["SRSNAME"] == urn, "a box without SRSNAME is widened to its WGS84 envelope"
    assert (float(xmin), float(ymin), float(xmax), float(ymax)) == pytest.approx(
        expected, rel=0, abs=1e-6
    )
    assert result.is_empty


def test_the_bbox_on_the_euhydro_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real ArcGIS discovery and query run; only their transport is canned."""
    wire.responses.extend(
        [
            _CannedResponse(
                payload={
                    "layers": [
                        {"id": 12, "type": "Group Layer", "name": "River_Net_lines"},
                        {"id": 13, "type": "Feature Layer", "parentLayerId": 12},
                    ]
                }
            ),
            _CannedResponse(payload={"name": "main"}),
            _CannedResponse(payload={"features": []}),
        ]
    )
    source = EuHydroSource()
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT_L93))

    assert all("image.discomap.eea.europa.eu" in call["url"] for call in wire.calls)
    query = wire.calls[-1]
    sent = query["params"]["geometry"].split(",")
    expected = _expected_bbox(CALLER_EXTENT_L93, source.extent_crs)
    assert tuple(float(value) for value in sent) == pytest.approx(expected, rel=0, abs=1e-6)
    assert result.is_empty


def test_the_bbox_on_the_osm_wire_is_the_reprojected_one(tmp_path: Path, wire: Wire) -> None:
    """The real Overpass query is built; only its HTTP request is canned."""
    wire.responses.append(_CannedResponse(content=b'{"elements": []}'))
    source = OsmSource(waterway_types=(("river", "canal")))
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT_L93))

    assert [call["url"] for call in wire.calls] == ["https://overpass-api.de/api/interpreter"]
    query = wire.calls[0]["params"]["data"]
    lon_min, lat_min, lon_max, lat_max = _expected_bbox(CALLER_EXTENT_L93, source.extent_crs)
    bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    assert bbox in query
    assert 'way["waterway"="river"]' in query
    assert 'way["waterway"="canal"]' in query
    assert result.is_empty


def test_the_bbox_on_the_ign_wire_is_the_reprojected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real RGE ALTI WMS assembly runs; only ``HTTPClient.request`` is canned.

    Every tile the plan asks for carries the snapped box of the request, so the
    reprojected extent is what reaches the wire, tile by tile, for a box that
    covers two departments offline.
    """
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    from hydromodpy.core.io.fetch import HTTPClient
    from hydromodpy.data.variables.dem.apis import geoplateforme_wms as wms

    sent: list[dict[str, Any]] = []

    def _request(_self: object, method: str, url: str, **kwargs: Any) -> Any:
        assert "data.geopf.fr" in url, f"unexpected host on wire: {url}"
        params = kwargs.get("params") or {}
        if params.get("REQUEST") != "GetMap":
            raise AssertionError(f"an unexpected request reached the wire: {url} {params}")
        sent.append(dict(params))
        width, height = int(params["WIDTH"]), int(params["HEIGHT"])
        bbox = tuple(float(v) for v in params["BBOX"].split(","))
        profile = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:2154",
            "transform": from_origin(bbox[0], bbox[3], 5.0, 5.0),
            "nodata": -99999.0,
        }
        with MemoryFile() as memory:
            with rasterio.open(memory, "w", **profile) as dst:
                dst.write(np.zeros((height, width), dtype="float32"), 1)
            payload = memory.read()

        class _Answer:
            content = payload
            status_code = 200
            headers: dict[str, str] = {}

            def raise_for_status(self) -> None:
                return None

            def close(self) -> None:
                return None

        return _Answer()

    monkeypatch.setattr(HTTPClient, "request", _request)

    caller = Extent(
        xmin=-2.0,
        ymin=48.0,
        xmax=-2.0 + 0.011,
        ymax=48.0 + 0.011,
        crs="EPSG:4326",
    )
    source = IgnGeoplateformeDem(dataset="rge-alti")
    result = source.fetch(FetchRequest(out_dir=tmp_path, extent=caller))

    expected = wms.snap_bbox(_expected_bbox(caller, source.extent_crs), 5.0)
    assert sent, "no tile request reached the wire"
    for params in sent:
        xmin, ymin, xmax, ymax = (float(v) for v in params["BBOX"].split(","))
        assert xmin >= expected[0] - 1e-6 and xmax <= expected[2] + 1e-6
        assert ymin >= expected[1] - 1e-6 and ymax <= expected[3] + 1e-6
        assert (xmax - xmin) / int(params["WIDTH"]) == pytest.approx(5.0)
    assert result.files, "the assembled raster came back as a files payload"


def test_reprojection_is_what_makes_the_dem_request_answerable() -> None:
    """``fetch_ign_dem`` resolves departments from a box in Lambert-93.

    Measured offline: the caller's WGS84 box over eastern Brittany resolves to
    **no department at all**, and the same box in Lambert-93 resolves to
    Cotes-d'Armor and Ille-et-Vilaine. A caller that forwarded the WGS84 box
    unchanged would not fetch the wrong tiles, it would raise ``No department
    found``.
    """
    from hydromodpy.catchment.administrative.france import find_departments_in_bbox

    assert find_departments_in_bbox(CALLER_EXTENT.bbox) == []
    assert find_departments_in_bbox(CALLER_EXTENT.to_crs("EPSG:2154").bbox) == [
        "022",
        "035",
    ]


def test_what_the_dem_download_makes_on_disk_lands_under_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DEM downloader, held to where it writes.

    The real ``fetch_ign_dem`` prologue runs -- department resolution,
    cache-key hashing, the ``mkdir`` of ``processed/`` -- and only the
    download step is replaced, by one that raises. Everything the function
    creates before reaching the network is then read back off disk.
    """
    from hydromodpy.data.variables.dem.apis import ign_dem_fr

    class _StopBeforeDownload(RuntimeError):
        pass

    def _refuse(**_kwargs: object) -> list[Path]:
        raise _StopBeforeDownload

    monkeypatch.setattr(ign_dem_fr, "download_ign_dem_departments", _refuse)

    workspace = tmp_path / "workspace"
    out_dir = workspace / "jobdir"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    with pytest.raises(_StopBeforeDownload):
        ign_dem_fr.fetch_ign_dem(output_dir=out_dir, bbox=CALLER_EXTENT.to_crs("EPSG:2154").bbox)

    assert out_dir.is_dir(), "the prologue never got as far as making the directory"
    assert sorted(p.name for p in workspace.iterdir()) == ["jobdir"], (
        "the prologue created something beside the directory it was given"
    )
    assert sorted(p.name for p in out_dir.rglob("*")) == ["processed"]


# --------------------------------------------------------------------------- #
# The doubles answer like the sources they stand for
# --------------------------------------------------------------------------- #


def test_a_record_the_source_does_not_declare_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result whose records carry a variable the instance does not serve is refused.

    ``variables`` is the instance's: a source configured for one product that
    received a record labeled with another would otherwise return a result
    whose own ``variables`` contradicts its records.
    """
    from dataclasses import dataclass as _dataclass

    @_dataclass
    class _MislabelledRecord:
        variable: str

    monkeypatch.setattr(
        sys.modules[__name__],
        "_gauge_provider",
        lambda **_kwargs: [_MislabelledRecord(variable="gauge_depth")],
    )
    with pytest.raises(DataProductError, match="gauge_depth"):
        _GaugeDouble().fetch(FetchRequest(out_dir=Path("."), extent=CALLER_EXTENT, period=PERIOD))


def test_the_bdtopage_defaults_match_the_config_they_replace() -> None:
    """Two copies of a default drift; this is the gate that says when."""
    from hydromodpy.data.variables.hydrography.apis.bdtopage import DEFAULT_PAGE_SIZE
    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

    assert DEFAULT_PAGE_SIZE == HydrographySourceConfig(source="bdtopage").page_size


# ---- installed-probe section ----
#
# The conformance suite of the data-source port reaches a source it does not name.
#
# ``add-a-data-source.rst`` tells a plugin author to run the suite from a clone, with the
# plugin installed. This file installs a source the suite has never heard of and runs the
# suite on it, in a subprocess because ``importlib.metadata`` reads the entry points once.
#
# The entry point of the probe carries the joined name the registry keys it on,
# ``<section>_<source_id>``: a third-party source serves a section of its own choosing --
# one no shipped TOML model describes -- and the name it is published under is the section
# and the id joined by ``_``, exactly the rule the solver backends follow.

# One worker runs the file, so the collection below runs once.

SUITE = "tests/ports/test_data_source.py"
PROBE_SECTION = "conformance-probe"
PROBE_ID = "conformance-probe-gauge"
PROBE_KEY = f"{PROBE_SECTION}_{PROBE_ID}"

PROBE_MODULE = """\\
from hydromodpy.data.source.port import require_period, require_selectors


class ProbeSource:
    source_id = "conformance-probe-gauge"
    section = "conformance-probe"
    payload_kind = "points"
    extent_crs = "EPSG:4326"
    selectors = ("extent",)
    period_need = "required"
    writes_out_dir = False
    variables = ("probe_level",)
    hosts = ("probe.example",)

    def fetch(self, request):
        require_selectors(self, request)
        require_period(self, request)
        raise AssertionError("the suite reached the provider of a source it cannot stub")
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"),
        "hmp_source_probe",
        PROBE_MODULE,
        "hydromodpy.data.source",
        PROBE_KEY,
        "ProbeSource",
    )  # fmt: skip


@pytest.mark.xdist_group("data_source_conformance_probe")
def test_the_suite_holds_an_installed_source_to_its_declarations_and_refusals(
    installed_probe: Path, tmp_path: Path
) -> None:
    listing = run_suite(SUITE, tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)  # fmt: skip
    assert listing.returncode == 0, listing.stdout[-4000:]
    nodes = [line for line in listing.stdout.splitlines() if PROBE_KEY in line]
    assert len(nodes) >= 6, listing.stdout[-8000:]
    # One test of the suite is a shipped-only one: the licence table has no
    # entry for a foreign source, and the suite skips it for one by design.
    shipped_only = [node for node in nodes if "reads_its_hosts_in_the_licence_table" in node]
    assert len(shipped_only) == 1, nodes

    result = run_suite(SUITE, tmp_path / "run", "-q", "-k", PROBE_KEY, site_packages=installed_probe)  # fmt: skip

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None and int(passed.group(1)) == len(nodes) - len(shipped_only), (
        result.stdout[-4000:]
    )


class _IdOnlyProbeSource:
    """The probe source, published under its id alone: a name that is not a key."""

    source_id: ClassVar[str] = PROBE_ID
    section: ClassVar[str] = PROBE_SECTION
    payload_kind: ClassVar[str] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "required"
    writes_out_dir: ClassVar[bool] = False
    variables: ClassVar[tuple[str, ...]] = ("probe_level",)
    hosts: ClassVar[tuple[str, ...]] = ("probe.example",)

    def fetch(self, request):  # pragma: no cover - never reached
        raise AssertionError("a source published under a name that is not its key answers nothing")


@pytest.mark.xdist_group("data_source_conformance_probe")
def test_a_probe_published_under_its_id_alone_registers_nothing(
    isolated_registry: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry-point name is the joined key; the class declares it and cannot diverge.

    A name that is not what the class declares is ignored with a warning, on the
    rule D21 set for the solver backends: the name is what a document writes,
    the id is what the run is stamped with, and two words for one plugin is how
    they start describing different things.
    """
    bare = EntryPoint(
        name=PROBE_ID,
        value="tests.stub:ProbeSource",
        group=registry.ENTRY_POINT_GROUP,
    )
    object.__setattr__(bare, "load", lambda: _IdOnlyProbeSource)
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        lambda *, group: (bare,),
    )
    with caplog.at_level("WARNING"):
        assert registry.data_sources.load_plugins() == 0
    assert PROBE_ID in caplog.text
    with pytest.raises(DataRequestError):
        registry.data_sources.get(PROBE_SECTION, PROBE_ID)
