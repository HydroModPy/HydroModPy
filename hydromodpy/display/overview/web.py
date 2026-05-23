"""Block-based HTML report for the overview workflow."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Any

from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.display.overview.summary import compute_overview_summary
from hydromodpy.display.report_blocks import (
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportMetric,
    ReportTable,
    write_report_page,
)

if TYPE_CHECKING:
    from hydromodpy.core.contracts.overview import DataOverviewState


def write_overview_web_report(
    state: DataOverviewState,
    *,
    figure_paths: list[Path],
    level: DetailLevel = "standard",
    output_path: Path | None = None,
) -> Path:
    """Write the canonical block-based overview HTML report."""
    if output_path is None:
        output_path = _resolve_web_output_path(state)
    blocks = build_overview_blocks(state, figure_paths=figure_paths, level=level)
    summary = compute_overview_summary(state)
    title = summary.watershed_name or "Vue donnees bassin"
    subtitle = f"Vue donnees du bassin - niveau {level}."
    return write_report_page(
        output_path=output_path,
        title=title,
        subtitle=subtitle,
        blocks=blocks,
        current_level=level,
        level_links=_overview_level_links(state)
        if _show_level_links(output_path=output_path)
        else None,
    )


def write_overview_review_web_reports(
    state: DataOverviewState,
    *,
    figure_paths: list[Path],
) -> list[Path]:
    """Write temporary compact/standard/audit review pages."""
    output_root = _resolve_web_output_path(state).parent.parent / "web_review"
    paths: list[Path] = []
    for level in ("compact", "standard", "audit"):
        paths.append(
            write_overview_web_report(
                state,
                figure_paths=figure_paths,
                level=level,
                output_path=output_root / level / "index.html",
            )
        )
    return paths


def build_overview_blocks(
    state: DataOverviewState,
    *,
    figure_paths: list[Path],
    level: DetailLevel = "standard",
) -> list[ReportBlock]:
    """Build reusable report blocks from one overview runtime state."""
    figure_by_id = {path.stem: path for path in figure_paths}
    blocks = [
        _workflow_header_block(state),
        _spatial_context_block(state, figure_by_id, level=level),
        _data_inventory_block(state, level=level),
        _observation_inventory_block(state, figure_by_id, level=level),
        _forcing_context_block(state, level=level),
        _artifact_links_block(state, figure_paths, level=level),
    ]
    return [block for block in blocks if _should_render_block(block)]


def _workflow_header_block(state: DataOverviewState) -> ReportBlock:
    summary = compute_overview_summary(state)
    workspace_root = "-"
    if state.workspace is not None:
        workspace_root = str(getattr(state.workspace, "project_root", "-"))

    return ReportBlock(
        block_id="workflow_header",
        title="Identite du workflow",
        level="compact",
        lead="Synthese minimale du rapport et de l'espace de travail.",
        metrics=(
            ReportMetric("Workflow", "overview"),
            ReportMetric("Bassin", summary.watershed_name or "-"),
            ReportMetric("Periode", _period_label(summary.date_start, summary.date_end)),
            ReportMetric("Espace de travail", workspace_root),
        ),
    )


def _spatial_context_block(
    state: DataOverviewState,
    figure_by_id: Mapping[str, Path],
    *,
    level: DetailLevel,
) -> ReportBlock:
    summary = compute_overview_summary(state)
    dg = state.domain_geographic
    geo_cfg = getattr(state.cfg, "geographic", None)
    crs = _first_non_empty(
        getattr(dg, "crs", None),
        getattr(dg, "target_crs", None),
        getattr(geo_cfg, "crs_project", None),
        "-",
    )
    metrics = [
        ReportMetric(
            "Surface bassin",
            _format_float(summary.catchment_area_km2, digits=2),
            "km2" if summary.catchment_area_km2 is not None else "",
        ),
        ReportMetric("CRS", crs),
    ]
    if level in ("standard", "audit"):
        metrics.append(
            ReportMetric(
                "Definition du bassin",
                _catchment_definition_label(getattr(geo_cfg, "catch_def", "")),
            )
        )
    regional_context = ReportFigure(
        "map_regional_context",
        _regional_context_title(state),
        figure_by_id.get("map_regional_context"),
        "",
        required=False,
    )
    dem_context = ReportFigure(
        "map_dem_context",
        "Domaine simule",
        figure_by_id.get("map_dem_context"),
        "",
    )
    observed_network = ReportFigure(
        "map_hydrography_data",
        "Reseau hydrographique observe",
        figure_by_id.get("map_hydrography_data"),
        "",
        required=False,
    )
    figures: tuple[ReportFigure, ...]
    if level == "compact":
        figures = _available_figures((dem_context, regional_context))
    else:
        if observed_network.available:
            figures = _available_figures((observed_network, regional_context))
        else:
            figures = _available_figures((dem_context, regional_context))
    warnings: tuple[str, ...] = ()
    return ReportBlock(
        block_id="spatial_context",
        title="Localisation",
        level=level,
        lead=_spatial_context_lead(
            level=level,
            has_observed_network=observed_network.available,
        ),
        metrics=tuple(metrics),
        figures=figures,
        warnings=warnings,
    )


def _spatial_context_lead(*, level: DetailLevel, has_observed_network: bool) -> str:
    if level in ("standard", "audit") and has_observed_network:
        return "Reseau hydrographique observe superpose au fond topographique."
    return "Situation regionale et emprise du bassin versant."


def _available_figures(figures: tuple[ReportFigure, ...]) -> tuple[ReportFigure, ...]:
    return tuple(figure for figure in figures if figure.available)


def _catchment_definition_label(value: Any) -> str:
    labels = {
        "from_outlet_coord": "Exutoire fourni",
        "from_watershed_file": "Contour de bassin fourni",
        "from_bbox": "Emprise fournie",
    }
    return labels.get(str(value), str(value).replace("_", " ") if value else "-")


def _regional_context_title(state: DataOverviewState) -> str:
    configured_label = getattr(getattr(state.cfg, "overview", None), "regional_context_label", None)
    if configured_label:
        return str(configured_label)
    candidates = [
        getattr(getattr(state, "domain_geographic", None), "regional_dem_path", None),
        getattr(getattr(state.cfg, "geographic", None), "dem_init_path", None),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        name = Path(candidate).stem.lower()
        if "armorican" in name or "armoricain" in name:
            return "Situation dans le Massif Armoricain"
        if "bretagne" in name or "brittany" in name:
            return "Situation en Bretagne"
    return "Situation regionale"


def _data_inventory_block(state: DataOverviewState, *, level: DetailLevel) -> ReportBlock:
    if level == "compact":
        return ReportBlock(
            block_id="data_inventory",
            title="Inventaire des donnees",
            level=level,
            status="not_applicable",
        )
    rows = tuple(_data_family_rows(state))
    columns: tuple[tuple[str, str], ...]
    if level == "compact":
        columns = (("family", "Famille"), ("status", "Statut"), ("records", "Objets"))
    else:
        columns = (
            ("family", "Famille"),
            ("status", "Statut"),
            ("sources", "Sources"),
            ("records", "Objets"),
            ("period", "Periode"),
        )
    return ReportBlock(
        block_id="data_inventory",
        title="Inventaire des donnees",
        level=level,
        lead="Familles de donnees demandees ou chargees par le workflow.",
        tables=(
            ReportTable(
                "data_family_table",
                "Familles de donnees",
                columns=columns,
                rows=rows,
                empty_message="Aucune famille de donnees demandee ou chargee.",
            ),
        ),
    )


def _observation_inventory_block(
    state: DataOverviewState,
    figure_by_id: Mapping[str, Path],
    *,
    level: DetailLevel,
) -> ReportBlock:
    ld = state.loaded_data
    rows = tuple(_station_inventory_rows(state))
    figures: tuple[ReportFigure, ...] = ()
    tables: tuple[ReportTable, ...] = ()
    if level in ("standard", "audit"):
        if rows:
            figures += (
                ReportFigure(
                    "station_inventory",
                    "Inventaire des stations",
                    figure_by_id.get("station_inventory"),
                    "Table image historique produite par le workflow overview.",
                    required=bool(rows),
                ),
            )
        if _point_count(ld.hydrometry) > 0:
            figures += (
                ReportFigure(
                    "timeseries_discharge",
                    "Debits observes",
                    figure_by_id.get("timeseries_discharge"),
                    "Chroniques hydrometriques observees, sans comparaison simulation.",
                    required=_point_count(ld.hydrometry) > 0,
                ),
            )
        if _point_count(ld.piezometry) > 0:
            figures += (
                ReportFigure(
                    "timeseries_piezometry",
                    "Niveaux piezometriques observes",
                    figure_by_id.get("timeseries_piezometry"),
                    "Chroniques piezometriques observees, si chargees.",
                    required=_point_count(ld.piezometry) > 0,
                ),
            )
        if _point_count(ld.intermittency) > 0:
            figures += (
                ReportFigure(
                    "timeseries_intermittency",
                    "Intermittence observee",
                    figure_by_id.get("timeseries_intermittency"),
                    "Chroniques ONDE ou intermittence, si chargees.",
                    required=_point_count(ld.intermittency) > 0,
                ),
            )
        if _point_count(ld.water_quality) > 0:
            figures += (
                ReportFigure(
                    "timeseries_water_quality",
                    "Qualite d'eau observee",
                    figure_by_id.get("timeseries_water_quality"),
                    "Chroniques qualite d'eau, si chargees.",
                    required=_point_count(ld.water_quality) > 0,
                ),
            )
        tables += (
            ReportTable(
                "station_inventory_table",
                "Stations observees",
                columns=(
                    ("type", "Type"),
                    ("id", "ID"),
                    ("x", "X"),
                    ("y", "Y"),
                    ("start", "Debut"),
                    ("end", "Fin"),
                ),
                rows=rows,
                empty_message="Aucune station observee chargee.",
            ),
        )
    if not rows and not any(
        _point_count(getattr(ld, attr, None)) > 0
        for attr in ("hydrometry", "piezometry", "intermittency", "water_quality")
    ):
        return ReportBlock(
            block_id="observation_inventory",
            title="Observations",
            level=level,
            status="not_applicable",
        )
    return ReportBlock(
        block_id="observation_inventory",
        title="Observations",
        level=level,
        lead="Stations et chroniques observees disponibles avant toute simulation.",
        metrics=(
            ReportMetric("Hydrometrie", _point_count(ld.hydrometry), "stations"),
            ReportMetric("Piezometrie", _point_count(ld.piezometry), "stations"),
            ReportMetric("Intermittence", _point_count(ld.intermittency), "stations"),
            ReportMetric("Qualite eau", _point_count(ld.water_quality), "stations"),
        ),
        figures=figures,
        tables=tables,
    )


def _forcing_context_block(state: DataOverviewState, *, level: DetailLevel) -> ReportBlock:
    recharge_mean = _recharge_mean_label(state.loaded_data.recharge)
    pumping = _pumping_summary(state)
    requested = {str(item).strip().lower() for item in getattr(state.cfg.data, "types", ())}
    if (
        state.loaded_data.recharge is None
        and "recharge" not in requested
        and pumping["well_count"] == 0
    ):
        return ReportBlock(
            block_id="forcing_context",
            title="Recharge et pompages",
            level=level,
            status="not_applicable",
        )
    warnings = []
    if state.loaded_data.recharge is None:
        warnings.append("Recharge non chargee.")
    if pumping["well_count"] == 0:
        warnings.append("Aucun pompage declare.")

    tables: tuple[ReportTable, ...] = ()
    if level in ("standard", "audit"):
        tables += (
            ReportTable(
                "recharge_source_table",
                "Sources recharge",
                columns=(("source", "Source"), ("period", "Periode"), ("path", "Chemin")),
                rows=tuple(_source_rows(getattr(state.cfg.data, "recharge", None))),
                empty_message="Aucune source recharge declaree.",
            ),
            ReportTable(
                "pumping_inventory_table",
                "Pompages declares",
                columns=(
                    ("well_id", "Ouvrage"),
                    ("location", "Localisation"),
                    ("mean_flux", "Flux moyen"),
                    ("units", "Unites"),
                ),
                rows=tuple(pumping["rows"]),
                empty_message="Aucun pompage declare.",
            ),
        )
    return ReportBlock(
        block_id="forcing_context",
        title="Recharge et pompages",
        level=level,
        lead="Entrees hydrologiques principales, vues comme donnees d'entree.",
        metrics=(
            ReportMetric("Recharge moyenne", recharge_mean),
            ReportMetric("Pompages", pumping["label"]),
            ReportMetric("Ouvrages", pumping["well_count"], "ouvrages"),
        ),
        tables=tables,
        warnings=tuple(warnings),
    )


def _artifact_links_block(
    state: DataOverviewState, figure_paths: list[Path], *, level: DetailLevel
) -> ReportBlock:
    if level != "audit":
        return ReportBlock(
            block_id="artifact_links",
            title="Artefacts",
            level=level,
            status="not_applicable",
        )
    rows = []
    for path in figure_paths:
        rows.append({"kind": "figure", "path": str(path)})
    config_path = getattr(state, "config_path", None)
    if config_path:
        rows.append({"kind": "config", "path": str(config_path)})
    return ReportBlock(
        block_id="artifact_links",
        title="Artefacts",
        level=level,
        lead="Fichiers produits ou references par le rapport.",
        tables=(
            ReportTable(
                "artifact_table",
                "Chemins",
                columns=(("kind", "Type"), ("path", "Chemin")),
                rows=tuple(rows),
                empty_message="Aucun artefact recense.",
            ),
        ),
    )


def _should_render_block(block: ReportBlock) -> bool:
    if not block.is_applicable:
        return False
    return bool(block.metrics or block.figures or block.tables or block.lead or block.warnings)


def _data_family_rows(state: DataOverviewState) -> list[dict[str, Any]]:
    requested = {str(item).strip().lower() for item in getattr(state.cfg.data, "types", ())}
    rows: list[dict[str, Any]] = []
    for family in _data_family_order(state):
        load_result = getattr(state.loaded_data, family, None)
        is_loaded = bool(load_result)
        if family not in requested and not is_loaded:
            continue
        section = getattr(state.cfg.data, family, None)
        rows.append(
            {
                "family": family,
                "status": "chargee" if is_loaded else "demandee",
                "sources": ", ".join(_source_names(section)) or "-",
                "records": _record_count_label(load_result),
                "period": _section_period(section) or _load_result_period(load_result) or "-",
            }
        )
    return rows


def _data_family_order(state: DataOverviewState) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for family in getattr(state.cfg.data, "types", ()) or ():
        name = str(family).strip().lower()
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    for field in fields(LoadedDataContext):
        if field.name not in seen:
            ordered.append(field.name)
            seen.add(field.name)
    return tuple(ordered)


def _station_inventory_rows(state: DataOverviewState) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for label, attr in (
        ("Hydrometrie", "hydrometry"),
        ("Piezometrie", "piezometry"),
        ("Intermittence", "intermittency"),
        ("Qualite eau", "water_quality"),
    ):
        load_result = getattr(state.loaded_data, attr, None)
        for record in getattr(load_result, "points", ()) or ():
            station_id = str(getattr(record, "station_id", ""))
            key = (label, station_id)
            loc = getattr(record, "location", None)
            start = _date_label(getattr(record, "date_start", None))
            end = _date_label(getattr(record, "date_end", None))
            if key not in rows_by_key:
                rows_by_key[key] = {
                    "type": label,
                    "id": station_id,
                    "x": _format_float(getattr(loc, "x", None), digits=1),
                    "y": _format_float(getattr(loc, "y", None), digits=1),
                    "start": start,
                    "end": end,
                }
                continue
            row = rows_by_key[key]
            if start and (not row["start"] or start < row["start"]):
                row["start"] = start
            if end and (not row["end"] or end > row["end"]):
                row["end"] = end
    return list(rows_by_key.values())


def _source_rows(section: Any) -> list[dict[str, Any]]:
    rows = []
    for source in getattr(section, "sources", ()) or ():
        rows.append(
            {
                "source": getattr(source, "source", "-"),
                "period": _period_label(
                    getattr(section, "date_start", ""),
                    getattr(section, "date_end", ""),
                ),
                "path": getattr(source, "path", "") or getattr(source, "mask_path", "") or "-",
            }
        )
    return rows


def _source_names(section: Any) -> list[str]:
    names = []
    for source in getattr(section, "sources", ()) or ():
        name = getattr(source, "source", "")
        if name:
            names.append(str(name))
    return names


def _section_period(section: Any) -> str:
    if section is None:
        return ""
    return _period_label(getattr(section, "date_start", ""), getattr(section, "date_end", ""))


def _load_result_period(load_result: Any) -> str:
    starts = []
    ends = []
    for record in getattr(load_result, "all_records", ()) or ():
        start = getattr(record, "date_start", None)
        end = getattr(record, "date_end", None)
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
    if not starts and not ends:
        return ""
    return _period_label(min(starts) if starts else "", max(ends) if ends else "")


def _record_count_label(load_result: Any) -> str:
    if not load_result:
        return "0"
    points = len(getattr(load_result, "points", ()) or ())
    fields = len(getattr(load_result, "fields", ()) or ())
    parts = []
    if points:
        parts.append(f"{points} point(s)")
    if fields:
        parts.append(f"{fields} champ(s)")
    if parts:
        return ", ".join(parts)
    try:
        return str(len(load_result))
    except Exception:
        return "1 objet"


def _point_count(load_result: Any) -> int:
    if load_result is None:
        return 0
    return len(getattr(load_result, "points", ()) or ())


def _recharge_mean_label(load_result: Any) -> str:
    values: list[float] = []
    units: list[str] = []
    for record in getattr(load_result, "points", ()) or ():
        data = getattr(record, "data", None)
        if data is None or "value" not in data:
            continue
        series = data["value"].dropna()
        if not series.empty:
            values.append(float(series.mean()))
            units.append(str(getattr(record, "unit", "") or ""))
    for record in getattr(load_result, "fields", ()) or ():
        mean_value = _field_mean(record)
        if mean_value is not None:
            values.append(mean_value)
            units.append(str(getattr(record, "unit", "") or ""))
    if not values:
        return "-"
    unit = units[0] if units else ""
    mean_value = fmean(values)
    if unit.lower() in {"mm/day", "mm d-1", "mm/d"}:
        return f"{mean_value * 365.25:.2f} mm/year"
    return f"{mean_value:.4g} {unit}".strip()


def _field_mean(record: Any) -> float | None:
    try:
        dataset = record.dataset
    except Exception:
        return None
    try:
        import numpy as np

        if hasattr(dataset, "data_vars"):
            arrays = [np.asarray(dataset[name].values, dtype=float) for name in dataset.data_vars]
        else:
            arrays = [np.asarray(dataset, dtype=float)]
        finite = [float(np.nanmean(array)) for array in arrays if array.size]
        finite = [value for value in finite if np.isfinite(value)]
        return fmean(finite) if finite else None
    except Exception:
        return None


def _pumping_summary(state: DataOverviewState) -> dict[str, Any]:
    wells = getattr(getattr(getattr(state.cfg, "flow", None), "sinks_sources", None), "wells", {})
    rows = []
    total_pumping = 0.0
    units = "m3/s"
    for well_id, well in (wells or {}).items():
        mean_flux = _mean_flux(getattr(well, "flux", None))
        units = str(getattr(well, "units", units) or units)
        if mean_flux is not None and mean_flux < 0:
            total_pumping += -mean_flux
        rows.append(
            {
                "well_id": well_id,
                "location": _well_location_label(getattr(well, "location", None)),
                "mean_flux": "-" if mean_flux is None else f"{mean_flux:.4g}",
                "units": units,
            }
        )
    if not rows:
        label = "-"
    elif units == "m3/s":
        label = f"{total_pumping:.4g} m3/s ({total_pumping * 86400.0:.4g} m3/day)"
    else:
        label = f"{total_pumping:.4g} {units}"
    return {"well_count": len(rows), "label": label, "rows": rows}


def _mean_flux(flux: Any) -> float | None:
    if flux is None:
        return None
    if isinstance(flux, (int, float)) and not isinstance(flux, bool):
        return float(flux)
    if isinstance(flux, (list, tuple)) and flux:
        return fmean(float(item) for item in flux)
    return None


def _well_location_label(location: Any) -> str:
    if location is None:
        return "-"
    kind = getattr(location, "kind", location.__class__.__name__)
    if hasattr(location, "x") and hasattr(location, "y"):
        return f"{kind} ({float(location.x):.1f}, {float(location.y):.1f})"
    if hasattr(location, "cell"):
        return f"{kind} {location.cell}"
    return str(kind)


def _period_label(start: Any, end: Any) -> str:
    start_label = _date_label(start)
    end_label = _date_label(end)
    if not start_label and not end_label:
        return "-"
    if start_label and end_label:
        return f"{start_label} -> {end_label}"
    return start_label or end_label


def _date_label(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "date"):
        try:
            return str(value.date())
        except Exception:
            pass
    return str(value)


def _format_float(value: Any, *, digits: int) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def _format_xy(value: tuple[float, float] | None) -> str:
    if value is None:
        return "-"
    return f"{value[0]:.1f}, {value[1]:.1f}"


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return "-"


def _resolve_web_output_path(state: DataOverviewState) -> Path:
    if state.workspace is not None and hasattr(state.workspace, "paths"):
        return state.workspace.paths.figures_folder.parent / "web" / "index.html"
    if state.workspace is not None:
        return Path(getattr(state.workspace, "project_root", ".")) / "web" / "index.html"
    return Path("web") / "index.html"


def _overview_level_links(state: DataOverviewState) -> dict[str, Path]:
    review_root = _resolve_web_output_path(state).parent.parent / "web_review"
    return {
        "compact": review_root / "compact" / "index.html",
        "standard": review_root / "standard" / "index.html",
        "audit": review_root / "audit" / "index.html",
    }


def _show_level_links(*, output_path: Path) -> bool:
    if output_path.parent.parent.name == "web_review":
        return True
    value = os.environ.get("HMP_OVERVIEW_HTML_REVIEW_LEVELS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "build_overview_blocks",
    "write_overview_review_web_reports",
    "write_overview_web_report",
]
