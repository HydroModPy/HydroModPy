"""Compare sealed runs of one site: what differs, when, where, and against the gauge.

The first run is the reference. Everything is read through the public ``Run``
API, so this file does not know how a run is stored. Two values are compared
only when they cover the same dates, and two maps only at the same date.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from hydromodpy.core.exceptions import ResultsError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.display.run_comparison import draw_maps, draw_series
from hydromodpy.project.facade import read_sealed_config
from hydromodpy.results.derive import views
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.run.tables import global_parameters
from hydromodpy.results.run.view import Run, open_run_dir

MAP_VARIABLES = ("watertable_elevation", "watertable_depth")
SERIES_VARIABLES = ("discharge", "head")
SCORES = ("nse", "kge", "bias")
NETWORK_ROLES = ("reference", "reference_permanent")
STEADY = pd.Timestamp("1970-01-01 00:00:01")
"""A steady run has no date that compares, so this stamp stands for its only step."""


class ComparisonCaseError(ResultsError, ValueError):
    """The runs cannot be compared, and the message says why."""


class ComparisonReferenceError(ResultsError, LookupError):
    """A reference names no sealed run."""


@dataclass(frozen=True)
class Comparison:
    """The tables of one comparison and the data of its figures."""

    runs: Sequence[Run]
    start: pd.Timestamp
    end: pd.Timestamp
    tables: dict[str, pd.DataFrame]
    series: dict[tuple[str, str], pd.DataFrame]
    maps: dict[str, tuple[pd.Timestamp, list[np.ndarray]]]

    def write(self, out: Path) -> Path:
        """Write the tables, the figures and the README into *out*, and return the README."""
        folder = Path(out).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        names = [run.name for run in self.runs]
        span = f"Dates compared {self.start.date()} to {self.end.date()}"
        dates = "Steady state" if self.end == STEADY else span
        lines = [f"# {' vs '.join(names)}", "", f"Reference {names[0]}. {dates}."]
        for name, table in self.tables.items():
            table.to_csv(folder / f"{name}.csv", index=False)
            lines += ["", f"## {name}", "", _markdown(table)]
        for (variable, station), frame in self.series.items():
            if len(frame) > 1:
                path = folder / f"{variable}_{station.strip('_')}.png"
                draw_series(frame, self.runs[0], variable, station, path)
                lines += ["", f"![{variable}]({path.name})"]
        for variable, (date, values) in self.maps.items():
            path = folder / f"{variable}.png"
            draw_maps(values, self.runs, variable, _shown(date), path)
            lines += ["", f"![{variable}]({path.name})"]
        readme = folder / "README.md"
        readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return readme


def compare(runs: Sequence[Run], variables: Sequence[str] | None = None) -> Comparison:
    """Compare *runs*, the first one as the reference."""
    if len(runs) < 2:
        raise ComparisonCaseError("A comparison needs at least two runs.")
    names = [run.name for run in runs]
    if len(set(names)) < len(names):
        raise ComparisonCaseError(f"The runs must have distinct names, got {names}.")
    if len({run.record.identity.site_fingerprint for run in runs}) > 1:
        sites = ", ".join(f"{run.name}: {run.site}" for run in runs)
        raise ComparisonCaseError(
            f"The runs model different sites ({sites}). Compare runs of one site, or "
            "pass --by site to compare the runs of each site."
        )
    start, end = common_window(runs)
    chosen = [v for v in variables or MAP_VARIABLES if all(r.has_field(v) for r in runs)]
    if variables and len(chosen) < len(variables):
        missing = sorted(set(variables) - set(chosen))
        raise ComparisonCaseError(f"{missing} are not fields of every compared run.")
    series_rows, series = series_table(runs, start, end)
    map_rows, maps = maps_table(runs, chosen)
    tables = {
        "runs": runs_table(runs),
        "parameters": parameters_table(runs),
        "scores": scores_table(runs),
        "budget": budget_table(runs, start, end),
        "network": network_table(runs),
        "series": series_rows,
        "maps": map_rows,
    }
    return Comparison(runs, start, end, tables, series, maps)


def _is_steady(run: Run) -> bool:
    return run.record.run.flow_regime == "steady"


def _stamps(run: Run) -> pd.DatetimeIndex:
    """Return the stamp that closes each step of *run*."""
    return pd.DatetimeIndex([STEADY]) if _is_steady(run) else run.time_index


def _bounds(run: Run) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the first and last date of *run*."""
    if _is_steady(run):
        return STEADY - pd.Timedelta(1, "s"), STEADY
    period = run.record.period
    return pd.Timestamp(period.start).tz_localize(None), pd.Timestamp(period.end).tz_localize(None)


def _shown(stamp: pd.Timestamp) -> str:
    return "steady" if stamp == STEADY else str(stamp)


def common_window(runs: Sequence[Run]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the dates every run covers, or refuse when there are none."""
    if len({_is_steady(run) for run in runs}) > 1:
        raise ComparisonCaseError("Steady and transient runs have no date in common.")
    bounds = [_bounds(run) for run in runs]
    start = max(first for first, _ in bounds)
    end = min(last for _, last in bounds)
    if start >= end:
        spans = ", ".join(
            f"{run.name}: {first.date()} to {last.date()}"
            for run, (first, last) in zip(runs, bounds, strict=True)
        )
        raise ComparisonCaseError(f"The runs share no date ({spans}).")
    return start, end


def whole_periods(run: Run, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Return the seconds of each period of *run* wholly inside the dates, by closing stamp."""
    closes = _stamps(run)
    opens = closes.insert(0, _bounds(run)[0])[:-1]
    inside = (opens >= start) & (closes <= end)
    return pd.Series((closes - opens)[inside].total_seconds(), index=closes[inside])


def period_means(series: pd.Series, opening: pd.Timestamp, stamps: pd.DatetimeIndex) -> pd.Series:
    """Average *series* over the periods *stamps* close, weighted by duration.

    A stamp closes its period, so a daily series and a monthly one compare on
    the months. On its own stamps a series comes back unchanged.
    """
    series = series[series.index > opening]
    edges = series.index.insert(0, opening)
    frame = pd.DataFrame(
        {
            "value": series.to_numpy(dtype=float),
            "duration": np.diff(edges) / np.timedelta64(1, "s"),
            "period": np.searchsorted(stamps, series.index),
        }
    ).dropna()
    frame = frame[frame["period"] < len(stamps)]
    frame["volume"] = frame["value"] * frame["duration"]
    grouped = frame.groupby("period")[["volume", "duration"]].sum()
    means = grouped["volume"] / grouped["duration"]
    return pd.Series(means.to_numpy(), index=stamps[means.index.to_numpy()], name=series.name)


def _read_series(run: Run, variable: str, station: str) -> pd.Series:
    series = run.timeseries(variable, station=station)
    return series.set_axis([STEADY]) if _is_steady(run) else series


def series_table(
    runs: Sequence[Run], start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.DataFrame, dict[tuple[str, str], pd.DataFrame]]:
    """Compare each series every run stores, on the coarsest whole periods among them."""
    rows, aligned = [], {}
    periods = min((whole_periods(run, start, end) for run in runs), key=len)
    if periods.empty:
        return pd.DataFrame(), {}
    stamps = periods.index
    opening = stamps[0] - pd.Timedelta(float(periods.iloc[0]), "s")
    for variable in SERIES_VARIABLES:
        for station in sorted(set.intersection(*(set(r.stations(variable)) for r in runs))):
            frame = pd.DataFrame(
                {
                    run.name: period_means(_read_series(run, variable, station), opening, stamps)
                    for run in runs
                }
            )
            aligned[(variable, station)] = frame
            reference = frame.iloc[:, 0]
            for name in frame.columns[1:]:
                rows.append(
                    {"variable": variable, "station": station, "run": name}
                    | {"reference": frame.columns[0]}
                    | {"first": _shown(stamps[0]), "last": _shown(stamps[-1])}
                    | _errors(frame[name] - reference, reference)
                )
    return pd.DataFrame(rows), aligned


def _errors(error: pd.Series, reference: pd.Series, weights=None) -> dict[str, float]:
    keep = np.isfinite(error)
    if not keep.any():
        return {"n": 0}
    used = None if weights is None else np.asarray(weights)[keep]
    return {
        "n": int(keep.sum()),
        "reference_mean": float(np.average(reference[keep], weights=used)),
        "bias": float(np.average(error[keep], weights=used)),
        "mae": float(np.average(np.abs(error[keep]), weights=used)),
        "rmse": float(np.sqrt(np.average(error[keep] ** 2, weights=used))),
    }


def maps_table(
    runs: Sequence[Run], variables: Sequence[str]
) -> tuple[pd.DataFrame, dict[str, tuple[pd.Timestamp, list[np.ndarray]]]]:
    """Compare each map at the last date all runs share, per unit of surface."""
    shared = _stamps(runs[0])
    for run in runs[1:]:
        shared = shared.intersection(_stamps(run))
    if shared.empty:
        return pd.DataFrame(), {}
    date = shared.max()
    reference = runs[0]
    centers = reference.mesh.cell_centers()
    areas = np.asarray(reference.mesh.cell_areas(), dtype=float)
    rows, maps = [], {}
    for variable in variables:
        values = [_on_reference(run, variable, date, centers, np.sqrt(areas)) for run in runs]
        maps[variable] = (date, values)
        for run, other in zip(runs[1:], values[1:], strict=True):
            same = run.record.identity.mesh_hash == reference.record.identity.mesh_hash
            rows.append(
                {"variable": variable, "date": _shown(date), "run": run.name}
                | {"reference": reference.name, "same_mesh": same}
                | _errors(pd.Series(other - values[0]), pd.Series(values[0]), areas)
            )
    return pd.DataFrame(rows), maps


def _on_reference(
    run: Run, variable: str, date: pd.Timestamp, centers: np.ndarray, sizes: np.ndarray
) -> np.ndarray:
    """Read *variable* at *date* at the cell nearest each reference cell, NaN when too far."""
    step = int(_stamps(run).get_loc(date))
    values = np.asarray(run.field(variable, time=step), dtype=float)
    if values.ndim != 1:
        raise ComparisonCaseError(f"{variable} is not one value per cell, so it has no map here.")
    distance, nearest = cKDTree(run.mesh.cell_centers()).query(centers)
    return np.where(distance <= sizes, values[nearest], np.nan)


def runs_table(runs: Sequence[Run]) -> pd.DataFrame:
    """One row per run: what it is and whether it closed its budget."""
    return pd.DataFrame(
        {
            "run": run.name,
            "solver": run.solver,
            "start": run.record.period.start,
            "end": run.record.period.end,
            "n_steps": len(_stamps(run)),
            "budget_pct": run.checks.budget_pct,
            "mesh": (run.record.identity.mesh_hash or "")[:8],
        }
        for run in runs
    )


def parameters_table(runs: Sequence[Run]) -> pd.DataFrame:
    """The parameters whose value differs between the runs, one column per run."""
    table = pd.DataFrame({run.name: pd.Series(global_parameters(run), dtype=float) for run in runs})
    return table[table.nunique(axis=1, dropna=False) > 1].rename_axis("parameter").reset_index()


def scores_table(runs: Sequence[Run]) -> pd.DataFrame:
    """The score of each run against its gauge, its window and its number of samples.

    A daily and a monthly score do not compare, and their samples show it.
    """
    frames = [
        run.metrics[run.metrics["metric"].isin(SCORES)].assign(run=run.name)
        for run in runs
        if not run.metrics.empty
    ]
    if not frames:
        return pd.DataFrame()
    columns = [
        "run",
        "station",
        "variable",
        "metric",
        "value",
        "window_start",
        "window_end",
        "n_samples",
    ]
    return pd.concat(frames, ignore_index=True)[columns]


def budget_table(runs: Sequence[Run], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Mean net flow of each budget term on the shared dates, zone by zone, never added.

    The term ``residual`` sums the others, storage included. It must be near zero
    on the model domain. On a catchment it also holds the lateral exchange.
    """
    rows = []
    for run in runs:
        budget = run.budget()
        if budget.empty:
            continue
        units = set(budget["unit"])
        if units != {"m3 s-1"}:
            raise ComparisonCaseError(f"{run.name} has budget rows in {sorted(units)}, not m3 s-1.")
        durations = whole_periods(run, start, end)
        weight = pd.Series(durations.to_numpy(), index=_stamps(run).get_indexer(durations.index))
        budget = budget[budget["timestep"].isin(weight.index)].copy()
        budget["net"] = (budget["flux_in"] - budget["flux_out"]) * budget["timestep"].map(weight)
        net = budget.groupby(["zone_id", "component"])["net"].sum() / weight.sum()
        for (zone, component), value in net.items():
            rows.append({"run": run.name, "zone": str(zone), "term": component, "m3_s": value})
        for zone, value in net.groupby(level="zone_id").sum().items():
            rows.append({"run": run.name, "zone": str(zone), "term": "residual", "m3_s": value})
    return pd.DataFrame(rows)


def network_table(runs: Sequence[Run]) -> pd.DataFrame:
    """How the cells that flow match each mapped network, one row per run and network."""
    rows = [
        {"run": run.name}
        | views.cell_field_network_overlap_metrics(run, network_role=role)
        | views.cell_field_network_distance_metrics(run, network_role=role)
        for run in runs
        for role in NETWORK_ROLES
        if run.has_field("drain_accumulation_flux") and run.has_hydrographic_network(role)
    ]
    kept = ("_ratio", "_median_m")
    table = pd.DataFrame(rows)
    return table[[c for c in table if c in ("run", "network_role") or c.endswith(kept)]]


def resolve_references(refs: Sequence[str], *, project_root: Path | None) -> list[list[Run]]:
    """Return the sealed runs each reference names, one list per reference.

    A run directory or a run name gives one run. A recipe gives the latest run
    of each of its cases.
    """
    resolved = []
    for ref in refs:
        runs_dir = None if project_root is None else runs_dir_for(project_root)
        directories = [Path(ref).expanduser()] + ([runs_dir / ref] if runs_dir else [])
        direct = [path for path in directories if is_sealed(path)]
        runs = (
            [open_run_dir(direct[0], read_config=read_sealed_config)]
            if direct
            else _latest_of_recipe(runs_dir, ref)
        )
        if not runs:
            where = f" under {runs_dir}" if runs_dir else ""
            raise ComparisonReferenceError(
                f"{ref!r} names no sealed run{where}: give a run directory, a run name such "
                "as base.v2, or a recipe of the project."
            )
        resolved.append(runs)
    return resolved


def _latest_of_recipe(runs_dir: Path | None, recipe: str) -> list[Run]:
    if runs_dir is None or not runs_dir.is_dir():
        return []
    sealed = [
        open_run_dir(path, read_config=read_sealed_config)
        for path in sorted(runs_dir.iterdir())
        if is_sealed(path)
    ]
    of_recipe = [run for run in sealed if run.record.run.recipe == recipe]
    latest = {
        run.record.run.case_id: run
        for run in sorted(of_recipe, key=lambda run: run.record.run.version)
    }
    return [latest[case] for case in sorted(latest)]


def compare_references(
    refs: Sequence[str], *, project_root: Path | None, variables: Sequence[str] | None = None
) -> Comparison:
    """Compare the runs *refs* name, the first one as the reference."""
    resolved = resolve_references(refs, project_root=project_root)
    return compare([run for runs in resolved for run in runs], variables)


def compare_by_site(
    refs: Sequence[str],
    out: Path,
    *,
    project_root: Path | None,
    variables: Sequence[str] | None = None,
) -> Path:
    """Compare the runs of each site two references hold, and join their scores."""
    groups: dict[str | None, list[Run]] = {}
    for runs in resolve_references(refs, project_root=project_root):
        sites = [run.site for run in runs]
        if len(set(sites)) < len(sites):
            raise ComparisonCaseError(
                "One reference holds two runs of one site: name the runs, not their recipe."
            )
        for run in runs:
            groups.setdefault(run.site, []).append(run)
    scores = []
    for site, runs in groups.items():
        if len(runs) > 1:
            comparison = compare(runs, variables)
            comparison.write(Path(out) / (site or "no_site"))
            scores.append(comparison.tables["scores"].assign(site=site))
    if not scores:
        raise ComparisonCaseError("No site holds a run in two of the references.")
    path = Path(out) / "by_site.csv"
    pd.concat(scores, ignore_index=True).to_csv(path, index=False)
    return path


def _markdown(table: pd.DataFrame) -> str:
    if table.empty:
        return "Nothing to compare."
    text = table.map(lambda value: f"{value:.4g}" if isinstance(value, float) else str(value))
    rows = [list(table.columns), ["---"] * table.shape[1], *text.to_numpy().tolist()]
    return "\n".join("| " + " | ".join(map(str, row)) + " |" for row in rows)
