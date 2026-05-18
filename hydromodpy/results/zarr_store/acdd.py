"""ACDD-1.3 root-attribute composition for Zarr stores.

Source of values is the DuckDB ``simulations`` row plus ``runs_environment``
plus an optional workspace ``[project]`` table parsed from ``workspace.toml``.
The composer is pure: it consumes plain dicts and returns a plain dict, so it
stays easy to unit-test and to drive from any catalog backend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hydromodpy.core.version import __version__ as _HMP_VERSION
from hydromodpy.results.zarr_store.constants import CF_CONVENTIONS, ZARR_SCHEMA_VERSION

# ACDD-1.3 Highly Recommended attributes (11 entries, per ACDD §2.6.1).
HIGHLY_RECOMMENDED = (
    "title",
    "summary",
    "keywords",
    "keywords_vocabulary",
    "Conventions",
    "id",
    "naming_authority",
    "creator_name",
    "creator_email",
    "creator_institution",
    "creator_url",
)


def _isoformat(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def compose_acdd_root_attrs(
    *,
    sim_row: dict[str, Any] | None,
    runs_env: dict[str, Any] | None,
    project_table: dict[str, Any] | None = None,
    geographic_bounds: dict[str, float] | None = None,
    history_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Return the ACDD/CF root attributes for one simulation.

    ``sim_row``: the ``simulations`` DB row as a dict. Recognised keys are
    ``sim_id``, ``name``, ``description``, ``project``, ``solver``,
    ``study_area_name``, ``period_start``, ``period_end``, ``time_unit``,
    ``crs_wkt``, ``crs_epsg``, ``bbox_xmin``, ``bbox_ymin``, ``bbox_xmax``,
    ``bbox_ymax``, ``contact_email``, ``doi``, ``scientific_objective``,
    ``creator_institution``, ``creator_url``, ``naming_authority``,
    ``keywords``, ``license``, ``processing_level``, ``time_coverage_duration``,
    ``time_coverage_resolution``.

    ``runs_env``: a ``runs_environment`` row dict. Recognised: ``user_name``,
    ``hostname``, ``hydromodpy_version``, ``git_commit``, ``rng_seed``,
    ``mf6_binary_sha256``, ``mf6_version_text``.

    ``project_table``: optional ``[project]`` block from ``workspace.toml``
    (creator_name, creator_email, license, etc.). Acts as a fallback when
    sim_row lacks a value.

    ``geographic_bounds``: optional ``{lat_min, lat_max, lon_min, lon_max,
    vertical_min, vertical_max}`` reprojected in WGS84 / metres.

    ``history_lines``: optional list of ISO-prefixed history entries; the
    composer adds the current ``finalize`` timestamp at the end.
    """
    sim = dict(sim_row or {})
    env = dict(runs_env or {})
    proj = dict(project_table or {})
    bounds = dict(geographic_bounds or {})

    def pick(key: str, *fallbacks: str) -> Any:
        for src in (sim, env, proj):
            value = src.get(key)
            if value not in (None, ""):
                return value
        for fb in fallbacks:
            for src in (sim, env, proj):
                value = src.get(fb)
                if value not in (None, ""):
                    return value
        return ""

    now_iso = datetime.now(UTC).isoformat()
    title = pick("title", "name") or f"HydroModPy run {str(sim.get('sim_id', ''))[:8]}"
    summary = pick("summary", "description", "scientific_objective") or (
        "HydroModPy distributed groundwater simulation."
    )
    keywords_default = "groundwater, hydrology"
    solver = sim.get("solver") or env.get("solver") or ""
    if solver:
        keywords_default = f"{keywords_default}, {solver}"
    keywords = pick("keywords") or keywords_default
    license_value = pick("license") or "CC-BY-4.0"

    history_chain = list(history_lines or [])
    history_chain.append(f"{now_iso}: hydromodpy finalize")
    history = " ; ".join(history_chain)

    duration_iso = pick("time_coverage_duration")
    resolution_iso = pick("time_coverage_resolution") or _iso_resolution(sim.get("time_unit"))

    source_parts = [f"HydroModPy {_HMP_VERSION}"]
    if env.get("mf6_version_text"):
        source_parts.append(str(env["mf6_version_text"]))
    elif solver:
        source_parts.append(str(solver))

    lat_min = float(bounds.get("lat_min", float("nan")))
    lat_max = float(bounds.get("lat_max", float("nan")))
    lon_min = float(bounds.get("lon_min", float("nan")))
    lon_max = float(bounds.get("lon_max", float("nan")))

    geospatial_bounds_wkt = _bounds_wkt(lat_min, lat_max, lon_min, lon_max)
    metadata_link = pick("metadata_link", "doi")
    comment = pick("comment", "scientific_objective", "description")

    attrs: dict[str, Any] = {
        # ACDD-1.3 + CF + UGRID declaration.
        "Conventions": CF_CONVENTIONS,
        # Highly Recommended (11).
        "title": str(title),
        "summary": str(summary),
        "keywords": str(keywords),
        "keywords_vocabulary": str(pick("keywords_vocabulary") or "GCMD Science Keywords"),
        "id": str(sim.get("sim_id") or ""),
        "naming_authority": str(pick("naming_authority") or "org.hydromodpy.catalog"),
        "creator_name": str(pick("creator_name", "user_name")),
        "creator_email": str(pick("creator_email", "contact_email")),
        "creator_institution": str(pick("creator_institution")),
        "creator_url": str(pick("creator_url")),
        # Recommended.
        "history": history,
        "source": "; ".join(source_parts),
        "references": str(pick("references", "doi")),
        "project": str(pick("project")),
        "processing_level": str(pick("processing_level") or "Modeled L2"),
        "license": str(license_value),
        "comment": str(comment),
        "date_modified": now_iso,
        "metadata_link": str(metadata_link),
        # Publisher trio (ACDD §2.6.4).
        "publisher_name": str(pick("publisher_name") or pick("creator_name", "user_name")),
        "publisher_email": str(pick("publisher_email", "creator_email", "contact_email")),
        "publisher_url": str(pick("publisher_url", "creator_url")),
        # Vocabularies (ACDD §2.6.3 + CF §2.6.1).
        "standard_name_vocabulary": str(
            pick("standard_name_vocabulary") or "CF Standard Name Table v85"
        ),
        "cdm_data_type": str(pick("cdm_data_type") or "Grid"),
        # Geospatial bounds (WGS84 by convention).
        "geospatial_lat_min": lat_min,
        "geospatial_lat_max": lat_max,
        "geospatial_lon_min": lon_min,
        "geospatial_lon_max": lon_max,
        "geospatial_vertical_min": float(bounds.get("vertical_min", float("nan"))),
        "geospatial_vertical_max": float(bounds.get("vertical_max", float("nan"))),
        # Units + resolution + bounds geometry (ACDD §2.6.4).
        "geospatial_lat_units": str(pick("geospatial_lat_units") or "degrees_north"),
        "geospatial_lat_resolution": str(pick("geospatial_lat_resolution")),
        "geospatial_lon_units": str(pick("geospatial_lon_units") or "degrees_east"),
        "geospatial_lon_resolution": str(pick("geospatial_lon_resolution")),
        "geospatial_vertical_units": str(pick("geospatial_vertical_units") or "m"),
        "geospatial_vertical_positive": str(pick("geospatial_vertical_positive") or "up"),
        "geospatial_bounds": geospatial_bounds_wkt,
        "geospatial_bounds_crs": str(pick("geospatial_bounds_crs") or "EPSG:4326"),
        # Temporal coverage.
        "time_coverage_start": _isoformat(sim.get("period_start")),
        "time_coverage_end": _isoformat(sim.get("period_end")),
        "time_coverage_duration": str(duration_iso),
        "time_coverage_resolution": str(resolution_iso),
        # HydroModPy-specific provenance (additive).
        "hydromodpy_version": str(env.get("hydromodpy_version") or _HMP_VERSION),
        "hydromodpy_git_commit": str(env.get("git_commit") or ""),
        "hydromodpy_solver": str(solver),
        "hydromodpy_solver_binary_sha256": str(env.get("mf6_binary_sha256") or ""),
        "hydromodpy_rng_seed": int(env["rng_seed"]) if env.get("rng_seed") is not None else -1,
        "zarr_schema_version": ZARR_SCHEMA_VERSION,
    }
    return attrs


def _bounds_wkt(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> str:
    """Build a 5-point POLYGON WKT from a lat/lon bounding box.

    Returns the empty string when any coordinate is NaN so downstream
    validators (cfchecker, stac-validator) can detect the missing value.
    """
    coords = (lat_min, lat_max, lon_min, lon_max)
    if any(coord != coord for coord in coords):  # NaN check
        return ""
    return (
        f"POLYGON(({lon_min} {lat_min}, {lon_max} {lat_min}, "
        f"{lon_max} {lat_max}, {lon_min} {lat_max}, {lon_min} {lat_min}))"
    )


def _iso_resolution(time_unit: Any) -> str:
    """Best-effort ISO 8601 duration for a HydroModPy time unit."""
    if time_unit is None:
        return ""
    name = str(time_unit).lower()
    return {
        "day": "P1D",
        "days": "P1D",
        "d": "P1D",
        "hour": "PT1H",
        "h": "PT1H",
        "minute": "PT1M",
        "m": "PT1M",
        "second": "PT1S",
        "s": "PT1S",
        "month": "P1M",
        "year": "P1Y",
    }.get(name, "")


__all__ = ["compose_acdd_root_attrs", "HIGHLY_RECOMMENDED"]
