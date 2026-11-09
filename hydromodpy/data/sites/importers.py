"""Turn a source of sites into :class:`SiteRow` rows.

Each importer reads one kind of source and stops at the rows: adding them to
the catalog is :func:`hydromodpy.data.sites.catalog.add_sites`. Three sources:

- a site table (CSV in the columns of ``SITE_ROW_COLUMNS``);
- a vector layer of outlets (one point per site, the name in a field);
- the Hub'Eau stations inside a box, optionally snapped onto a river network.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.site import SITE_ROW_COLUMNS, SiteRow

if TYPE_CHECKING:
    import geopandas as gpd

StationDiscovery = Callable[..., list[dict]]
"""Finds the Hub'Eau reference rows inside a WGS84 box."""

HUBEAU_DEFAULT_CRS = "EPSG:2154"
"""CRS of the box and of the outlets of a Hub'Eau import when none is named."""


@dataclass(frozen=True, slots=True)
class SiteImport:
    """The rows an importer read, and what it skipped with the reason."""

    rows: tuple[SiteRow, ...]
    skipped: tuple[str, ...] = field(default=())


def site_name(text: str) -> str:
    """Return ``text`` as a site name: every other character than ``[A-Za-z0-9_]`` becomes ``_``."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(text).strip()).strip("_")
    if not name:
        raise ValueError(f"{text!r} holds no character a site name can keep.")
    return name


def rows_from_table(path: Path) -> SiteImport:
    """Read a CSV site table in the columns of ``SITE_ROW_COLUMNS``."""
    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise ValueError(
            f"{source}: a site table is a CSV file in the columns "
            f"{', '.join(SITE_ROW_COLUMNS)}. Import a vector layer with --layer."
        )
    rows: list[SiteRow] = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        for line, record in enumerate(csv.DictReader(handle), start=2):
            try:
                rows.append(SiteRow.from_mapping(record))
            except ValueError as exc:
                raise ValueError(f"{source}:{line}: {exc}") from exc
    return SiteImport(rows=tuple(rows))


def rows_from_layer(
    path: Path,
    *,
    name_field: str,
    gauge_field: str | None = None,
    label_field: str | None = None,
    layer: str | None = None,
) -> SiteImport:
    """Read a vector layer of outlets: one point per site, named by ``name_field``."""
    import geopandas as gpd

    frame = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"{path}: the layer declares no CRS; an outlet needs one.")
    for column in (name_field, gauge_field, label_field):
        if column is not None and column not in frame.columns:
            fields = ", ".join(str(name) for name in frame.columns if name != "geometry")
            raise ValueError(f"{path}: no field {column!r}; the fields are {fields}.")
    crs = frame.crs.to_string()
    rows: list[SiteRow] = []
    for index, record in frame.iterrows():
        geometry = record.geometry
        if geometry is None or geometry.geom_type != "Point":
            raise ValueError(
                f"{path}: feature {index} is a {getattr(geometry, 'geom_type', 'missing')} "
                "geometry; an outlet layer holds points."
            )
        rows.append(
            SiteRow(
                site=site_name(record[name_field]),
                label=_cell(record, label_field),
                gauge=_cell(record, gauge_field),
                x_outlet=float(geometry.x),
                y_outlet=float(geometry.y),
                crs=crs,
            )
        )
    return SiteImport(rows=tuple(rows))


def rows_from_hubeau(
    bbox: Sequence[float],
    *,
    crs: str = HUBEAU_DEFAULT_CRS,
    min_years: float | None = None,
    snap_network: Path | str | None = None,
    snap_max_m: float = 200.0,
    snap_output_dir: Path | None = None,
    discover: StationDiscovery | None = None,
    today: date | None = None,
) -> SiteImport:
    """Read the Hub'Eau discharge stations inside a box, one site per Hub'Eau site.

    ``bbox`` is ``xmin, ymin, xmax, ymax`` in ``crs``; the outlets come out in
    the same CRS. The site is the Hub'Eau site code (8 characters), the gauge
    the station code (10 characters) and the URI ``hubeau:<site code>``; a
    site with several stations keeps the first one. ``min_years`` keeps the
    stations open for at least that many years, closing date or today.
    ``snap_network`` (a vector file, or ``bdtopage``) moves each outlet onto
    the nearest line within ``snap_max_m``; a
    station farther away is skipped and named.
    """
    from pyproj import Transformer

    from hydromodpy.data.variables.hydrometry.apis.hubeau import discover_stations

    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    box = to_wgs84.transform_bounds(xmin, ymin, xmax, ymax, densify_pts=21)
    stations = (discover or discover_stations)(box)
    from_wgs84 = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    current = today or datetime.now(UTC).date()

    rows: list[SiteRow] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for station in stations:
        code = str(station.get("code_station") or "").strip()
        site_code = str(station.get("code_site") or code[:8]).strip()
        lon, lat = station.get("longitude_station"), station.get("latitude_station")
        if not code or lon is None or lat is None:
            skipped.append(f"station {code or '?'}: no code or no coordinates")
            continue
        if site_code in seen:
            continue
        years = _open_years(station, today=current)
        if min_years is not None and (years is None or years < min_years):
            shown = "unknown" if years is None else f"{years:.1f}"
            skipped.append(f"station {code}: open {shown} years, under --min-years {min_years:g}")
            continue
        x, y = from_wgs84.transform(float(lon), float(lat))
        seen.add(site_code)
        rows.append(
            SiteRow(
                site=site_name(site_code),
                label=_text(station.get("libelle_station")),
                gauge=code,
                uri=f"hubeau:{site_code}",
                x_outlet=float(x),
                y_outlet=float(y),
                crs=crs,
            )
        )
    if snap_network is not None and rows:
        rows, far = _snap(
            rows,
            network=snap_network,
            max_distance_m=snap_max_m,
            crs=crs,
            output_dir=snap_output_dir,
        )
        skipped.extend(far)
    return SiteImport(rows=tuple(rows), skipped=tuple(skipped))


def fetch_bdtopage_reference_network(
    bbox_wgs84: tuple[float, float, float, float],
    *,
    page_size: int,
) -> gpd.GeoDataFrame:
    """Download the BD Topage reaches inside *bbox_wgs84*, in EPSG:4326, to snap outlets on.

    This is the fetcher of the outlet snap.
    """
    from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch
    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

    return fetch(HydrographySourceConfig(source="bdtopage", page_size=page_size), bbox_wgs84)


def _snap(
    rows: list[SiteRow],
    *,
    network: Path | str,
    max_distance_m: float,
    crs: str,
    output_dir: Path | None,
) -> tuple[list[SiteRow], list[str]]:
    """Move each outlet onto the nearest line of a river network, or skip it."""
    from dataclasses import replace

    from hydromodpy.data.sites.outlet_snap import load_network, snap_outlet

    source = "bdtopage" if str(network) == "bdtopage" else "file"
    outlets = [(float(row.x_outlet), float(row.y_outlet)) for row in rows]
    if source == "bdtopage" and output_dir is None:
        raise ValueError("snapping onto bdtopage needs a folder to cache the network in.")
    loaded = load_network(
        source=source,
        outlets=outlets,
        target_crs=crs,
        output_dir=output_dir or Path("."),
        fetcher=fetch_bdtopage_reference_network,
        path=None if source == "bdtopage" else Path(network),
    )
    snapped: list[SiteRow] = []
    far: list[str] = []
    for row, outlet in zip(rows, outlets, strict=True):
        try:
            x, y = snap_outlet(
                row.site, outlet, loaded, crs=crs, max_distance_m=max_distance_m, source=source
            )
        except ValueError as exc:
            far.append(f"site {row.site}: {exc}")
            continue
        snapped.append(replace(row, x_outlet=x, y_outlet=y))
    return snapped, far


def _open_years(station: Mapping[str, Any], *, today: date) -> float | None:
    """Years between the opening of a station and its closing, or today."""
    opened = _date(station.get("date_ouverture_station"))
    if opened is None:
        return None
    closed = _date(station.get("date_fermeture_station")) or today
    return (closed - opened).days / 365.25


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _cell(record: Any, column: str | None) -> str | None:
    return None if column is None else _text(record[column])


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in {"", "nan", "None"} else text


def _number(value: Any) -> float | None:
    text = _text(value)
    return None if text is None else float(text)


__all__ = [
    "HUBEAU_DEFAULT_CRS",
    "SiteImport",
    "StationDiscovery",
    "fetch_bdtopage_reference_network",
    "rows_from_hubeau",
    "rows_from_layer",
    "rows_from_table",
    "site_name",
]
