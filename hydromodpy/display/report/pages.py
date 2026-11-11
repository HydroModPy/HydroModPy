"""The blocks of the report pages: a sealed run, its data overview and a calibration session.

Each function returns a list of blocks for ``engine.write_pages``. Nothing here
writes HTML and no sentence is written here: the caller gives the texts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import WORKSPACE_DATA_DIRNAME
from hydromodpy.core.units.quantities import SECONDS_PER_DAY
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.report.engine import (
    Block,
    Level,
    Link,
    Metric,
    Picture,
    Prose,
    Table,
    pairs_table,
)
from hydromodpy.display.report.presets import PRESETS, SHEET_FIGURES, Preset, ReportTexts
from hydromodpy.results.run.tables import read_run_table

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run
    from hydromodpy.results.session.view import Session

logger = get_logger(__name__)

TRIAL_ROWS_SHOWN = 20
_SCORE_COLUMNS = (
    ("station", "Station"),
    ("variable", "Variable"),
    ("metric", "Metric"),
    ("window_name", "Window"),
    ("value", "Value"),
    ("n_samples", "Samples"),
)
_INPUT_COLUMNS = (
    ("variable", "Input"),
    ("provider", "Provider"),
    ("path", "Path"),
    ("license", "Licence"),
)
_SHEET_SCORE_KEYS = ("station", "variable", "metric", "window", "value", "samples")
_SHEET_INPUT_KEYS = ("input", "provider", "path", "licence")
_STATION_FAMILIES = (
    ("hydrometry", "Hydrometry"),
    ("piezometry", "Piezometry"),
    ("intermittency", "Intermittency"),
    ("water_quality", "Water quality"),
)
_CATCHMENT_DEFINITIONS = {
    "from_outlet_coord": "Outlet provided",
    "from_watershed_file": "Catchment outline provided",
    "from_bbox": "Bounding box provided",
}
_SERIES_PANELS = (
    ("timeseries_piezometry", "Observed piezometric levels", "piezometry"),
    ("timeseries_intermittency", "Observed intermittency", "intermittency"),
    ("timeseries_water_quality", "Observed water quality", "water_quality"),
)
_SOURCE_COLUMNS = (("source", "Source"), ("period", "Period"), ("path", "Path"))
_INVENTORY_COLUMNS = (
    ("family", "Family"),
    ("source", "Source"),
    ("name", "Name"),
    ("records", "Records"),
    ("first", "First"),
    ("last", "Last"),
    ("mean_value", "Mean"),
    ("unit", "Unit"),
)


def run_blocks(
    run: Run,
    *,
    overview: Run | None,
    texts: ReportTexts,
    station: str | None,
    preset: Preset = PRESETS["research"],
) -> list[Block]:
    """Return the blocks of the research report of a sealed run.

    ``overview`` is the sealed data overview of the same site, or ``None``. Its
    panels fill the context blocks, and a panel it lacks is a required figure
    missing. The scores of every station are listed, the series and the headline
    read ``station``, or the gauge of the site when it is ``None``.
    """
    record = run.record
    site = record.site
    gauge = station or (None if site is None else site.gauge)
    at = {name: level for level, names in preset.figures.items() for name in names}
    figures = run.dir / "figures"
    panels = None if overview is None else overview.dir / "figures"
    sim, obs = _discharge(run, gauge)

    def panel(name: str, title: str, level: Level = "compact") -> tuple[Level, Picture]:
        path = None if panels is None else panels / f"{name}.png"
        return level, Picture(
            name, title, path, required=overview is not None and name in preset.panels
        )

    def drawn(name: str, title: str, required: bool = True) -> tuple[Level, Picture]:
        return at[name], Picture(name, title, figures / f"{name}.png", required=required)

    params = _parameters(run)
    scores = _scores_table(run)
    config = run.config_snapshot or {}
    river = _dig(config, "geographic", "river_network")
    return [
        _method_block(texts),
        Block(
            "site_context",
            "Site",
            "Identification of the catchment and of the data available for it.",
            items=(
                ("compact", Metric("Site", _site_name(run, gauge))),
                ("standard", Metric("CRS", getattr(site, "crs", None) or "")),
                ("standard", Metric("Outlet X", _num(getattr(site, "x_outlet", None)), "m")),
                ("standard", Metric("Outlet Y", _num(getattr(site, "y_outlet", None)), "m")),
                ("standard", Metric("Window", _window(run))),
                ("standard", Metric("Run cells", run.n_cells)),
                ("standard", _configuration_table(run, config)),
                panel("stats_card", "Data identity card"),
                drawn("watershed_id_card", "Catchment identity card"),
                panel("station_inventory", "Station inventory", "standard"),
            ),
        ),
        Block(
            "hydraulic_properties",
            "Hydraulic properties",
            "Hydraulic parameters used by the simulation.",
            items=(
                *(
                    ("compact", Metric(n, _num(v), u))
                    for n, v, u in params
                    if n in ("K", "Sy", "Ss")
                ),
                (
                    "standard",
                    pairs_table(
                        "parameters",
                        "Values",
                        [(n, f"{_num(v)} {u}".strip()) for n, v, u in params],
                    ),
                ),
            ),
        ),
        Block(
            "spatial_context",
            "Spatial context: DEM and geology",
            "Regional setting, relief and geology.",
            items=(
                panel("map_regional_context", "Regional context"),
                panel("map_dem", "DEM, catchment and outlet"),
                panel("map_geology", "Catchment geology", "standard"),
                ("standard", _geology_table(run, overview)),
            ),
        ),
        Block(
            "hydrographic_network",
            "Observed and generated hydrographic network",
            "Reference hydrography and its comparison with the simulated network.",
            items=(
                ("compact", Metric("Reference segments", _reference_segments(run))),
                (
                    "standard",
                    Metric(
                        "DEM extraction threshold",
                        _num(_dig(river, "threshold_area_km2")),
                        "km2",
                    ),
                ),
                ("audit", Metric("Source figures folder", str(figures))),
                panel("map_hydrography", "Reference hydrographic network"),
                drawn("hydrographic_network_generated", "DEM-generated network", False),
                drawn(
                    "hydrographic_network_comparison", "Reference and DEM network comparison", False
                ),
                drawn(
                    "hydrographic_network_reference_missing_only",
                    "Reference segments the DEM network misses",
                    False,
                ),
                drawn(
                    "hydrographic_network_generated_extra_only",
                    "Generated segments outside the reference",
                    False,
                ),
                drawn("network_extent_bounds_map", "Yearly extent bounds against the map"),
                drawn("hydrographic_network_permanence", "Network permanence"),
                drawn(
                    "simulated_active_network_reference_overlay",
                    "Simulated network over the reference",
                ),
            ),
        ),
        Block(
            "simulation_network_outputs",
            "Simulated active network and seepage",
            "Seepage, persistence and intermittence of the network.",
            items=(
                drawn("seepage_map", "Seepage map"),
                drawn("flow_persistence_map", "Flow persistence"),
                drawn("flow_intermittence_map", "Flow intermittence"),
                drawn("seepage_network_confusion_map", "Seepage against the mapped network"),
                drawn("downslope_distance_map", "Downslope distance"),
            ),
        ),
        Block(
            "forcing_flux_context",
            "Fluxes, observed discharge and forcings",
            "Observed discharge, simulated discharge and climate of the window.",
            items=(
                ("compact", Metric("Forcing origin", _forcing_origin(config))),
                ("compact", Metric("Gauge", gauge or "")),
                ("compact", Metric("Mean observed discharge", _mean(obs), "m3/s")),
                ("audit", Metric("Observed discharge points", 0 if obs is None else len(obs))),
                panel("timeseries_discharge", "Observed discharge", "compact"),
                drawn("flux_timeseries", "Fluxes in and out"),
                panel("climatic_summary", "Monthly climatology", "audit"),
                ("audit", _series_table(sim, obs)),
            ),
        ),
        Block(
            "simulation_outputs",
            "Simulated fluxes",
            "Hydrograph, scores, head map and water budget.",
            items=(
                drawn("hydrograph_sim_obs", "Simulated hydrograph"),
                drawn("hydrograph_log_nse", "Hydrograph on a log axis"),
                drawn("piezometric_map", "Piezometric map"),
                drawn("water_budget", "Water budget"),
                ("standard", scores),
                drawn("watertable_depth_map", "Water table depth"),
                drawn("cross_section", "Cross-section"),
                ("audit", Metric("Simulation", run.name)),
                ("audit", Metric("Timesteps", run.n_timesteps)),
                ("audit", Metric("Mean simulated discharge", _mean(sim), "m3/s")),
                ("audit", Metric("Run time", _num(getattr(record.run, "duration_s", None)), "s")),
            ),
        ),
        Block(
            "artifacts",
            "Artifacts and limits",
            "Files of the run and where its inputs came from.",
            min_level="audit",
            items=(
                *(
                    ("audit", Link(name, run.dir / name, "json"))
                    for name in ("manifest.json", "inputs.json", "provenance.json", "outcome.json")
                    if (run.dir / name).is_file()
                ),
                ("audit", Link("config.toml", run.dir / "config.toml", "toml")),
                *(("audit", Link(path.name, path, "export")) for path in run.exports),
                ("audit", _inputs_table(run, "Inputs")),
            ),
        ),
    ]


def sheet_blocks(run: Run, *, texts: ReportTexts, station: str | None) -> list[Block]:
    """Return the blocks of the one-page sheet of a sealed run, in the language of ``texts``.

    The headline score is the score of the seal (``record.score``), the one
    ``results.score`` gives. ``station`` is kept for the caller and does not
    change the headline.
    """
    titles = texts.titles
    figures = run.dir / "figures"
    undetermined = tuple(
        f"{entry.variable}: {titles['licence_unknown']}"
        for entry in run.inputs
        if not entry.license or entry.license == UNDETERMINED_LICENSE
    )
    score = run.record.score
    headline = (
        ()
        if score is None
        else (
            {
                "station": score.station or "",
                "variable": score.variable or "",
                "metric": score.metric,
                "window": score.window_name or "",
                "value": _num(score.value),
                "samples": score.n_samples,
            },
        )
    )
    inputs = tuple(
        {"input": e.variable, "provider": e.provider, "path": e.path, "licence": e.license or ""}
        for e in run.inputs
    )
    return [
        Block("label", titles["label"], items=(("compact", Prose((texts.label,))),)),
        Block(
            "method",
            titles["method"],
            items=(("compact", Prose(_method_paragraphs(texts, without_label=True))),),
        ),
        Block(
            "figures",
            titles["figures"],
            items=tuple(
                ("compact", Picture(n, titles[f"figure_{n}"], figures / f"{n}.png", required=True))
                for n in SHEET_FIGURES
            ),
        ),
        Block(
            "scores",
            titles["scores"],
            items=(
                (
                    "compact",
                    Table(
                        "scores",
                        "",
                        tuple((k, titles[f"column_{k}"]) for k in _SHEET_SCORE_KEYS),
                        headline,
                        titles["no_score"],
                    ),
                ),
            ),
        ),
        Block(
            "inputs",
            titles["inputs"],
            items=(
                (
                    "compact",
                    Table(
                        "inputs",
                        "",
                        tuple((k, titles[f"column_{k}"]) for k in _SHEET_INPUT_KEYS),
                        inputs,
                        titles["no_input"],
                    ),
                ),
                *(("compact", w) for w in undetermined),
            ),
        ),
    ]


def overview_blocks(overview: Run) -> list[Block]:
    """Return the blocks of the data overview page, read from the sealed overview run."""
    figures = overview.dir / "figures"
    inventory = read_run_table(overview, "data_inventory")
    families = inventory[inventory["row_kind"] == "family"] if len(inventory) else inventory
    stations = inventory[inventory["row_kind"] == "station"] if len(inventory) else inventory
    wells = inventory[inventory["row_kind"] == "well"] if len(inventory) else inventory
    site = overview.record.site
    config = overview.config_snapshot or {}
    data = _dig(config, "data")
    hydrography = _family_row(families, "hydrography")
    recharge = _family_row(families, "recharge")
    pumping = _family_row(families, "pumping")
    area = getattr(site, "area_km2", None)

    def panel(name: str, title: str, level: Level = "compact") -> tuple[Level, Picture]:
        return level, Picture(
            name, title, figures / f"{name}.png", required=name in PRESETS["research"].panels
        )

    def listing(id: str, title: str, rows: pd.DataFrame) -> Table:
        return Table(id, title, _INVENTORY_COLUMNS, _records(rows), "Nothing loaded.")

    def count(family: str) -> int:
        return int((stations["family"] == family).sum()) if len(stations) else 0

    return [
        Block(
            "workflow_header",
            "Workflow identity",
            "Minimal summary of the report and of the workspace.",
            items=(
                ("compact", Metric("Workflow", "overview")),
                ("compact", Metric("Catchment", getattr(site, "label", None) or overview.name)),
                ("compact", Metric("Overview", overview.name)),
                ("compact", Metric("Period", _overview_period(overview, config, families))),
                ("compact", Metric("Workspace", str(overview.dir.parent.parent))),
                ("compact", Metric("Families", len(families))),
                ("compact", Metric("Stations", len(stations))),
            ),
        ),
        Block(
            "spatial_context",
            "Location",
            "Regional setting and extent of the catchment.",
            items=(
                (
                    "compact",
                    Metric("Catchment area", _num(area), "km2" if area is not None else ""),
                ),
                ("compact", Metric("CRS", getattr(site, "crs", None) or "")),
                (
                    "standard",
                    Metric(
                        "Catchment definition",
                        _catchment_definition(_dig(config, "geographic", "catchment", "kind")),
                    ),
                ),
                panel("map_dem", "Simulated domain"),
                panel("map_regional_context", "Regional context"),
                panel("map_geology", "Catchment geology", "standard"),
            ),
        ),
        Block(
            "hydrographic_network",
            "Hydrographic network",
            "Observed network, hydrography sources and map check.",
            items=(
                ("compact", Metric("Objects", _value(hydrography, "records", 0))),
                ("compact", Metric("Sources", _value(hydrography, "source", "") or "-")),
                ("compact", Metric("Period", _row_period(hydrography))),
                panel("map_hydrography", "Observed hydrographic network"),
                (
                    "audit",
                    _sources_table(
                        "hydrography_sources", "Hydrography sources", data, "hydrography"
                    ),
                ),
            ),
        ),
        Block(
            "data_inventory",
            "Data inventory",
            "Data families loaded by the workflow.",
            min_level="standard",
            items=(("standard", listing("families", "Data families", families)),),
        ),
        Block(
            "observation_inventory",
            "Observations",
            "Observed stations and series available before any simulation.",
            items=(
                *(
                    ("compact", Metric(label, count(family), "stations"))
                    for family, label in _STATION_FAMILIES
                ),
                panel("stats_card", "Data identity card"),
                panel("station_inventory", "Station inventory", "standard"),
                panel("timeseries_discharge", "Observed discharge", "standard"),
                *(
                    (
                        "standard",
                        Picture(name, title, figures / f"{name}.png", required=count(family) > 0),
                    )
                    for name, title, family in _SERIES_PANELS
                ),
                ("standard", listing("stations", "Stations", stations)),
            ),
        ),
        Block(
            "forcing_context",
            "Recharge and pumping",
            "Main hydrological inputs, seen as input data.",
            items=(
                ("compact", Metric("Mean recharge", _mean_label(recharge))),
                ("compact", Metric("Pumping", _pumping_label(pumping))),
                ("compact", Metric("Wells", len(wells), "wells")),
                panel("climatic_summary", "Monthly climatology", "standard"),
                (
                    "standard",
                    _sources_table("recharge_sources", "Recharge sources", data, "recharge"),
                ),
                ("standard", listing("wells", "Pumping wells", wells)),
            ),
        ),
        Block(
            "artifacts",
            "Artifacts",
            "Files produced or referenced by the report.",
            min_level="audit",
            items=(
                ("audit", _artifact_table(overview)),
                ("audit", _inputs_table(overview, "Inputs")),
            ),
        ),
    ]


def session_blocks(
    session: Session,
    *,
    summary_rows: Sequence[tuple[str, str]],
    figures: Sequence[Path],
    cases: Sequence[Mapping[str, str]] = (),
    best_figures: Sequence[Path] = (),
) -> list[Block]:
    """Return the blocks of the page of a calibration session.

    ``summary_rows`` are the rows ``results.session.summary`` writes, ``figures``
    the figures drawn for the session. ``cases`` has one row per calibrated case
    (``case``, ``site``, ``best_run``, ``note``), the note saying why a best run
    is not shown. ``best_figures`` are the figures of the best runs, shown at
    the audit level. This function opens no run, so a session of several cases
    or a best run that does not open still has its page.
    """
    trials = session.trials
    shown = trials.head(TRIAL_ROWS_SHOWN)
    columns = (
        ("trial", "Trial"),
        ("cost", "Cost"),
        ("status", "Status"),
        ("parameters", "Parameters"),
    )
    hidden = len(trials) - len(shown)
    case_columns = (
        ("case", "Case"),
        ("site", "Site"),
        ("best_run", "Best run"),
        ("note", "Note"),
    )
    return [
        Block(
            "summary",
            "Summary",
            items=(
                ("compact", pairs_table("session", "", list(summary_rows))),
                ("compact", Table("cases", "Cases", case_columns, tuple(cases), "No case.")),
            ),
        ),
        Block(
            "figures",
            "Figures",
            "" if len(figures) else "No figures rendered.",
            items=(
                *(("compact", Picture(p.stem, p.stem, p)) for p in figures),
                *(
                    ("audit", Picture(f"best_{p.stem}", f"best run: {p.stem}", p))
                    for p in sorted(best_figures)
                ),
            ),
        ),
        Block(
            "trials",
            f"Iteration trace (first {TRIAL_ROWS_SHOWN} rows)",
            f"{hidden} more rows not shown." if hidden > 0 else "",
            items=(
                ("compact", Table("trials", "", columns, _trial_rows(shown), "No iterations.")),
                ("audit", Table("trials_all", "All trials", columns, _trial_rows(trials))),
                (
                    "audit",
                    Table(
                        "phases",
                        "Phases",
                        (
                            ("phase", "Phase"),
                            ("status", "Status"),
                            ("stop", "Stop"),
                            ("best", "Best cost"),
                        ),
                        tuple(
                            {
                                "phase": p.name,
                                "status": p.status,
                                "stop": p.stop_state,
                                "best": _num(p.best.cost) if p.best else "",
                            }
                            for p in session.phases
                        ),
                    ),
                ),
            ),
        ),
    ]


def draw_named_figures(run: Run, names: Sequence[str]) -> tuple[str, ...]:
    """Draw the figures of ``names`` the run has not drawn; return the names drawn.

    Each missing figure goes into ``figures/`` of the run with the ``[display]``
    the run sealed. That folder is outside the seal. A figure the run cannot
    feed is skipped with its reason in the log, and its frame stays empty.
    """
    from hydromodpy.display.runs import figures_dir_of, log_render_summary, render_figures_for_run

    target = figures_dir_of(run.dir)
    missing = [name for name in dict.fromkeys(names) if not (target / f"{name}.png").is_file()]
    if not missing:
        return ()
    report = render_figures_for_run(
        run, _sealed_display(run, missing), output_dir=target, figure_names=missing
    )
    log_render_summary(report, destination=target)
    return tuple(report.rendered)


def _sealed_display(run: Run, figures: list[str]) -> DisplayConfig:
    """Return the ``[display]`` the run sealed, set to draw ``figures`` and save them.

    Only a value away from its default counts as set, as ``hmp show --figure`` reads
    it. The report always draws, headless, and a figure that fails is logged and
    skipped. A sealed ``[display]`` that no longer loads gives the defaults.
    """
    from hydromodpy.display.runs import sealed_display_values

    sealed = sealed_display_values(run.config_snapshot) or {}
    drawing = {
        "enabled": True,
        "save": True,
        "show": False,
        "backend": "agg",
        "on_error": "warn",
        "figures": figures,
    }
    try:
        return DisplayConfig.model_validate({**sealed, **drawing})
    except ValueError as exc:
        logger.warning(
            "Report: the [display] of this run no longer loads (%s); its figures use the defaults.",
            exc,
        )
        return DisplayConfig.model_validate(drawing)


def _method_block(texts: ReportTexts) -> Block:
    return Block(
        "method",
        texts.titles.get("method", "Method"),
        items=(("compact", Prose(_method_paragraphs(texts, without_label=False))),),
    )


def _method_paragraphs(texts: ReportTexts, *, without_label: bool) -> tuple[str, ...]:
    """Return the paragraphs of the method text; the label sentence goes when shown apart.

    The method text already carries the label in its quality paragraph, so the
    research page shows it once there, and the sheet, which has its own label
    block, drops it from the method.
    """
    paragraphs = [part.strip() for part in texts.method.split("\n\n") if part.strip()]
    if without_label and texts.label:
        paragraphs = [part.replace(texts.label, "").strip() for part in paragraphs]
    return tuple(part for part in paragraphs if part)


def _num(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}g}"
    except (TypeError, ValueError):
        return "" if value is None else str(value)


def _mean(series: pd.Series | None) -> str:
    return "" if series is None or series.empty else _num(series.mean())


def _site_name(run: Run, gauge: str | None) -> str:
    site = run.record.site
    label = getattr(site, "label", None) or getattr(site, "name", None) or run.name
    return f"{label} ({gauge})" if gauge else str(label)


def _window(run: Run) -> str:
    period = run.record.period
    if period is None or period.start is None or period.end is None:
        return "steady"
    return f"{period.start:%Y-%m-%d} to {period.end:%Y-%m-%d}, {period.time_unit}"


def _parameters(run: Run) -> list[tuple[str, Any, str]]:
    frame = run.parameters
    if frame is None or frame.empty:
        return []
    return [
        (str(name), row["value"], str(row.get("unit", "") or "")) for name, row in frame.iterrows()
    ]


def _discharge(run: Run, station: str | None) -> tuple[pd.Series | None, pd.Series | None]:
    """Return the simulated and the observed discharge of ``station``, ``None`` for a missing one."""
    sim = None
    if run.has_table("timeseries"):
        try:
            sim = run.timeseries("discharge", station=station)
        except KeyError:
            # The run stored no discharge at this station: the page shows no series.
            sim = None
    obs = None
    try:
        frame = run.observed("discharge", station=station)
    except (KeyError, ValueError):
        # No observation for this station: the page shows no observed series.
        frame = None
    if frame is not None and len(frame):
        obs = frame.set_index(pd.to_datetime(frame["datetime"]))["value"]
    return sim, obs


def _series_table(sim: pd.Series | None, obs: pd.Series | None) -> Table:
    rows = tuple(
        {
            "label": label,
            "rows": len(s),
            "start": s.index.min(),
            "end": s.index.max(),
            "mean": _num(s.mean()),
            "min": _num(s.min()),
            "max": _num(s.max()),
            "unit": "m3/s",
        }
        for label, s in (("Observed discharge", obs), ("Simulated discharge", sim))
        if s is not None and len(s)
    )
    columns = (
        ("label", "Series"),
        ("rows", "Points"),
        ("start", "Start"),
        ("end", "End"),
        ("mean", "Mean"),
        ("min", "Min"),
        ("max", "Max"),
        ("unit", "Unit"),
    )
    return Table("flux_stats", "Series", columns, rows)


def _scores_table(run: Run, *, title: str = "Scores on the scoring window") -> Table:
    """List every score of every station, each with the window it was read on."""
    rows = tuple(
        {**row, "value": _num(row["value"]), "n_samples": _count(row.get("n_samples"))}
        for row in _records(run.metrics)
    )
    return Table("scores", title, _SCORE_COLUMNS, rows, "No score on this run.")


def _count(value: Any) -> str:
    """Return a count as an integer, empty when it is missing."""
    if value is None or pd.isna(value):
        return ""
    return str(int(value))


def _dig(mapping: Any, *keys: str) -> Any:
    """Return the value at ``keys`` of nested mappings, ``None`` when a key is missing."""
    for key in keys:
        if not isinstance(mapping, Mapping):
            return None
        mapping = mapping.get(key)
    return mapping


def _first_source(config: Mapping[str, Any], family: str, key: str) -> Any:
    sources = _dig(config, "data", family, "sources")
    if isinstance(sources, list) and sources and isinstance(sources[0], Mapping):
        return sources[0].get(key)
    return None


def _configuration_table(run: Run, config: Mapping[str, Any]) -> Table:
    """Return the reference configuration: config file, DEM, thickness and drainage."""
    return pairs_table(
        "configuration",
        "Reference configuration",
        (
            ("Base config", str(run.dir / "config.toml")),
            ("DEM", _first_source(config, "dem", "path") or ""),
            ("Thickness", _num(_dig(config, "domain", "depth_model", "thickness"))),
            ("Drainage", _num(_dig(config, "flow", "bc", "drainage", "value"))),
        ),
    )


def _forcing_origin(config: Mapping[str, Any]) -> str:
    """Return the stations the recharge and the runoff were read at."""
    parts = []
    for family in ("recharge", "runoff"):
        ids: list[str] = []
        for source in _dig(config, "data", family, "sources") or ():
            if isinstance(source, Mapping):
                ids.extend(str(item) for item in source.get("station_ids") or ())
        if ids:
            parts.append(f"custom {family} ({', '.join(ids)})")
    return "; ".join(parts) if parts else "custom forcings"


def _reference_segments(run: Run) -> int | str:
    """Return the number of segments of the reference network the run stored."""
    frame = read_run_table(run, "geographic_hydrographic_network_reference")
    return len(frame) if len(frame) else "unknown"


def _geology_table(run: Run, overview: Run | None) -> Table:
    """Return the geological codes of the catchment, with their notation and area."""
    columns = (
        ("code", "Code"),
        ("notation", "Notation"),
        ("description", "Nature / description"),
        ("area_km2", "Approx. area (km2)"),
    )
    return Table(
        "geology_units",
        "Geological codes present",
        columns,
        _geology_rows(run, overview),
        "No geological code available.",
    )


def _geology_rows(run: Run, overview: Run | None) -> tuple[dict[str, Any], ...]:
    """Read the geology the run or its overview loaded, else the geology cache of the project.

    The map is clipped to the catchment the run stored. The first map that
    covers it gives the rows.
    """
    project = run.dir.parent.parent
    candidates = [
        path
        for source in (run, overview)
        if source is not None
        for entry in source.inputs
        if entry.variable == "geology"
        for path in (Path(entry.path), source.dir / entry.path, project / entry.path)
        if path.is_file()
    ]
    cache = project / WORKSPACE_DATA_DIRNAME / "geology"
    for pattern in ("geology_brgm_50k_*.gpkg", "geology_brgm_1m_*.gpkg"):
        found = (p for p in cache.glob(pattern) if p.name != "geology_brgm_1m_france.gpkg")
        candidates += sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return ()
    try:
        watershed = run.geographic("watershed")
    except (KeyError, OSError, ValueError) as exc:
        logger.info("Report: no stored catchment to clip the geology with (%s).", exc)
        watershed = None
    for path in dict.fromkeys(candidates):
        rows = _legend_rows(path, watershed)
        if rows:
            return rows
    return ()


def _legend_rows(path: Path, watershed: Any) -> tuple[dict[str, Any], ...]:
    import geopandas as gpd

    try:
        geology = gpd.read_file(path)
        if watershed is not None and len(watershed):
            shape = watershed.to_crs(geology.crs).geometry.union_all()
            geology = geology[geology.intersects(shape)].copy()
            geology["geometry"] = geology.geometry.intersection(shape)
    except Exception as exc:  # a broken map gives no legend; the report goes on
        logger.warning("Report: geology file %s could not be read: %s", path, exc)
        return ()
    if geology.empty:
        return ()
    code = _column(geology, ("CODE_LEG", "code_leg", "CODE", "geology_code"))
    if code is None:
        return ()
    notation = _column(geology, ("NOTATION", "notation", "LITHOLOGIE", "lithologie"))
    description = _column(
        geology, ("DESCR", "description", "NATURE", "LITHOLOGIE", "LITHO_SIMP", "lithologie")
    )
    frame = pd.DataFrame(
        {
            "code": geology[code].astype(str),
            "notation": geology[notation].astype(str) if notation else "",
            "description": geology[description].astype(str) if description else "",
            "area": geology.geometry.area / 1_000_000.0,
        }
    )
    grouped = frame.groupby(["code", "notation", "description"], dropna=False)["area"].sum()
    grouped = grouped.reset_index()
    grouped["order"] = pd.to_numeric(grouped["code"], errors="coerce")
    grouped = grouped.sort_values(["order", "code", "notation"], na_position="last")
    return tuple(
        {
            "code": row.code,
            "notation": row.notation,
            "description": row.description,
            "area_km2": f"{float(row.area):.2f}",
        }
        for row in grouped.itertuples()
    )


def _column(frame: pd.DataFrame, names: Sequence[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _family_row(families: pd.DataFrame, family: str) -> Mapping[str, Any] | None:
    if not len(families):
        return None
    rows = families[families["family"] == family]
    return None if rows.empty else rows.iloc[0].to_dict()


def _value(row: Mapping[str, Any] | None, key: str, default: Any) -> Any:
    if row is None:
        return default
    value = row.get(key)
    return default if value is None or (isinstance(value, float) and pd.isna(value)) else value


def _period(first: Any, last: Any) -> str:
    def day(value: Any) -> str:
        if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "":
            return ""
        try:
            return str(pd.Timestamp(value).date())
        except (TypeError, ValueError):
            # A date the config wrote in another form is shown as written.
            return str(value)

    start, end = day(first), day(last)
    if start and end:
        return f"{start} -> {end}"
    return start or end or "-"


def _row_period(row: Mapping[str, Any] | None) -> str:
    return "-" if row is None else _period(row.get("first"), row.get("last"))


def _overview_period(overview: Run, config: Mapping[str, Any], families: pd.DataFrame) -> str:
    """Return the period of the overview, as declared, else the span of its families."""
    start = _dig(config, "overview", "date_start")
    end = _dig(config, "overview", "date_end")
    if start or end:
        return _period(start, end)
    first, last = families.get("first"), families.get("last")
    if first is None or last is None or not len(families):
        return "-"
    return _period(first.min(), last.max())


def _catchment_definition(kind: Any) -> str:
    if not kind:
        return "-"
    return _CATCHMENT_DEFINITIONS.get(str(kind), str(kind).replace("_", " "))


def _mean_label(row: Mapping[str, Any] | None) -> str:
    value = _value(row, "mean_value", None)
    if value is None:
        return "-"
    return f"{float(value):.4g} {_value(row, 'unit', '')}".strip()


def _pumping_label(row: Mapping[str, Any] | None) -> str:
    total = _value(row, "mean_value", None)
    if total is None:
        return "-"
    unit = _value(row, "unit", "")
    if unit == "m3/s":
        return f"{float(total):.4g} m3/s ({float(total) * SECONDS_PER_DAY:.4g} m3/day)"
    return f"{float(total):.4g} {unit}".strip()


def _sources_table(id: str, title: str, data: Any, family: str) -> Table:
    """Return the declared sources of one data family: name, period and path."""
    rows = tuple(
        {
            "source": source.get("source", ""),
            "period": _period(source.get("date_start"), source.get("date_end")),
            "path": source.get("path") or "",
        }
        for source in _dig(data, family, "sources") or ()
        if isinstance(source, Mapping)
    )
    return Table(id, title, _SOURCE_COLUMNS, rows, f"No {family} source declared.")


def _artifact_table(overview: Run) -> Table:
    """Return the figures and the configuration of the overview, with their paths."""
    rows = [{"kind": "figure", "path": str(path)} for path in sorted(overview.figures)]
    config = overview.dir / "config.toml"
    if config.is_file():
        rows.append({"kind": "config", "path": str(config)})
    return Table(
        "artifact_table",
        "Paths",
        (("kind", "Type"), ("path", "Path")),
        tuple(rows),
        "No artifact listed.",
    )


def _inputs_table(run: Run, title: str) -> Table:
    rows = tuple(
        {"variable": e.variable, "provider": e.provider, "path": e.path, "license": e.license or ""}
        for e in run.inputs
    )
    return Table("inputs", title, _INPUT_COLUMNS, rows, "No input recorded.")


def _records(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    return tuple(frame.to_dict("records"))


def _trial_rows(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "trial": row.trial,
            "cost": "" if row.cost is None or pd.isna(row.cost) else f"{row.cost:.6g}",
            "status": row.status,
            "parameters": json.dumps(_parameter_values(row.parameters), sort_keys=True),
        }
        for row in frame.itertuples()
    )


def _parameter_values(parameters: Any) -> dict[str, Any]:
    if not isinstance(parameters, Mapping):
        return {}
    return {k: v.get("value") if isinstance(v, Mapping) else v for k, v in parameters.items()}
