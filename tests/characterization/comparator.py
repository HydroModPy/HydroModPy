"""Double-execution comparator: run one project twice, compare within tolerances.

The comparator answers one question before a refactor touches anything: *does
this project still produce the same numbers?* It runs a project twice, then
compares the two run directories field by field, table by table.

It never compares digests. Two executions of the same pinned solver agree bit
for bit on a structured grid, but the mesh generator breaks ties on
floating-point comparisons and a threaded solve reduces in thread order, so a
digest comparator would be red on its first day and stay red, and nobody would
read it again. Every verdict here is a band from ``tests/TOLERANCES.md``
(rows 69 to 72), and every band carries its rationale there.

Three comparison modes, chosen per array and reported:

``exact``
    integer, boolean and string arrays: connectivity, indices, labels. A
    reordered mesh connectivity is a real difference, not a rounding one.
``elementwise``
    float arrays of identical shape: the honest case, ``max |a - b|`` against
    ``atol + rtol * max |b|``.
``signature``
    float arrays whose shapes differ, which happens when the mesh itself moved.
    Falls back to ``count / mean / p50 / p95 / sum``, the same five statistics
    the regression tier already uses, compared on a looser band.

Usage::

    python -m tests.characterization.comparator --frozen --report out.md
    python -m tests.characterization.comparator --project path/to/project.toml
    python -m tests.characterization.comparator --compare runs/a runs/b

Exit codes: 0 every project inside its bands, 1 at least one drift or error,
2 a usage problem (missing project, missing run directory).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Single source of truth for every band below: tests/TOLERANCES.md.
from tests._helpers.tolerances import tol  # noqa: E402

FIELD_RTOL = tol("double_execution_comparator_float_arrays__rtol")
FIELD_ATOL = tol("double_execution_comparator_float_arrays__atol")
SIGNATURE_RTOL = tol("double_execution_comparator_signature_fallback__rtol")
SCALAR_RTOL = tol("double_execution_comparator_manifest_scalars__rtol")

FROZEN_PROJECTS: tuple[str, ...] = (
    "examples/projects/00_getting_started/project.toml",
    "examples/projects/02_basic_features_and_overview_of_possibilities/project.toml",
    "examples/projects/05_piezometry_in_a_heterogeneous_coastal_aquifer/project.toml",
    "examples/projects/04_streamflow_intermittence_in_transient/project.toml",
)
"""The four frozen projects of the characterization net.

Chosen for coverage per second, and all four committed: a synthetic structured
grid on MODFLOW-NWT; a small conceptual DEM through WhiteboxTools delineation,
MODFLOW 6 and particle tracking; a real coastal DEM over a heterogeneous
aquifer; and a monthly transient run on a regional DEM. Steady and transient,
synthetic and delineated, both flow engines. Together they run twice in about
three and a half minutes, which is what makes the comparator something a
session actually runs before touching anything.
"""

# Columns whose value is a new identity or a wall clock at every execution.
# Comparing them would make every report red and useless; the report lists
# what it dropped so the omission stays visible.
_VOLATILE_COLUMN_NAMES = frozenset(
    {
        "sim_id",
        "run_id",
        "step_id",
        "parent_sim_id",
        "uuid",
        "created_at",
        "updated_at",
        "started_at",
        "ended_at",
        "duration_s",
        "inputs_hash",
        "outputs_hash",
        "checkpoint_path",
        "artifact_uris",
        "config_sha256",
        "hostname",
        "user_name",
        "workspace",
        "project_root",
        "path",
        "valid_from",
        # Identity the comparator itself changes: the two executions are told
        # apart by their run name, so everything derived from that name moves.
        "name",
        "name_stem",
        "storage_basename",
        "config_toml",
        "config_snapshot",
        "config_source",
    }
)

# Metric rows that record how long the machine took, not what the model
# computed. Selected by metric NAME: the `runtime` variable bucket they sit in
# also carries `water_budget_percent_discrepancy`, which is exactly the kind of
# number this comparator exists to watch.
_VOLATILE_METRIC_SUFFIXES = ("_time_seconds", "_duration_s", "_elapsed_s")

# Manifest keys worth comparing: the ones a reader would use to decide that two
# runs describe the same physical object.
_MANIFEST_SCALAR_KEYS: tuple[tuple[str, ...], ...] = (
    ("manifest_version",),
    ("run", "solver"),
    ("run", "flow_regime"),
    ("geometry", "n_cells"),
    ("geometry", "n_layers"),
    ("geometry", "mesh_topology"),
    ("geometry", "crs_epsg"),
    ("geometry", "crs_wkt"),
    ("geometry", "bbox"),
    ("geometry", "catchment", "catch_area"),
    ("geometry", "catchment", "dem_res"),
    ("geometry", "catchment", "ncol"),
    ("geometry", "catchment", "nrow"),
    ("period", "n_timesteps"),
    ("period", "time_unit"),
)
"""Manifest keys a reader would use to decide two runs describe the same object.

``mesh_hash`` and ``config.hash`` are deliberately absent: a digest is the one
comparison this comparator refuses to make.
"""

_MANIFEST_LIST_KEYS: tuple[tuple[str, ...], ...] = (
    ("inputs",),
    ("artifacts",),
    ("parameters",),
    ("metrics",),
)


@dataclass(frozen=True)
class Verdict:
    """One comparison line of the report."""

    target: str
    kind: str  # field | table | manifest | structure
    mode: str  # exact | elementwise | signature | presence
    detail: str
    max_abs: float | None
    max_rel: float | None
    within: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "kind": self.kind,
            "mode": self.mode,
            "detail": self.detail,
            "max_abs": self.max_abs,
            "max_rel": self.max_rel,
            "within": self.within,
        }


@dataclass
class RunComparison:
    """Everything the comparator learned about one pair of run directories."""

    label: str
    run_a: Path
    run_b: Path
    verdicts: list[Verdict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dropped_columns: set[str] = field(default_factory=set)
    seconds_a: float = 0.0
    seconds_b: float = 0.0

    @property
    def drifted(self) -> list[Verdict]:
        return [verdict for verdict in self.verdicts if not verdict.within]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.drifted

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "run_a": str(self.run_a),
            "run_b": str(self.run_b),
            "seconds_a": self.seconds_a,
            "seconds_b": self.seconds_b,
            "ok": self.ok,
            "errors": self.errors,
            "notes": self.notes,
            "dropped_columns": sorted(self.dropped_columns),
            "verdicts": [verdict.as_dict() for verdict in self.verdicts],
        }


def _relative_gap(a: float, b: float) -> float:
    """Return the relative gap between two scalars, safe near zero."""
    scale = max(abs(a), abs(b))
    if scale == 0.0:
        return 0.0
    return abs(a - b) / scale


_SIGNATURE_COMPARED = ("mean", "p50", "p95", "min", "max")
"""Statistics compared when two arrays no longer share a shape.

``count`` and ``sum`` are reported but never compared: they move with the cell
count by construction, and a cell count that moved is already stated in the
verdict line. What must not move is the distribution, tails included - ``min``
and ``max`` are there because a regression on a handful of cells barely moves a
domain-wide mean. This mode remains the weaker of the three, and the verdict
line says so: it is what is left when the mesh itself moved.
"""


def _signature(values: np.ndarray) -> dict[str, float]:
    """Return the five statistics used when two arrays no longer share a shape."""
    flat = np.asarray(values, dtype=float).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return dict.fromkeys(("count", "mean", "p50", "p95", "min", "max", "sum"), 0.0)
    return {
        "count": float(finite.size),
        "mean": float(finite.mean()),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "min": float(finite.min()),
        "max": float(finite.max()),
        "sum": float(finite.sum()),
    }


def compare_arrays(
    target: str,
    a: np.ndarray,
    b: np.ndarray,
    *,
    kind: str = "field",
    rtol: float = FIELD_RTOL,
    atol: float = FIELD_ATOL,
    signature_rtol: float = SIGNATURE_RTOL,
) -> Verdict:
    """Compare two arrays and return the verdict line describing the outcome."""
    a = np.asarray(a)
    b = np.asarray(b)

    if a.dtype.kind not in "fc" or b.dtype.kind not in "fc":
        if a.shape != b.shape:
            return Verdict(
                target, kind, "exact", f"shape {a.shape} vs {b.shape}", None, None, False
            )
        equal = bool(np.array_equal(a, b))
        return Verdict(target, kind, "exact", f"{a.dtype} {a.shape}", None, None, equal)

    if a.shape != b.shape:
        sig_a, sig_b = _signature(a), _signature(b)
        gaps = {name: _relative_gap(sig_a[name], sig_b[name]) for name in _SIGNATURE_COMPARED}
        worst_name = max(gaps, key=lambda name: gaps[name])
        worst = gaps[worst_name]
        return Verdict(
            target,
            kind,
            "signature",
            f"shape {a.shape} vs {b.shape}, {sig_a['count']:.0f} vs {sig_b['count']:.0f} "
            f"finite values, worst stat {worst_name}",
            None,
            worst,
            worst <= signature_rtol,
        )

    finite_a = np.isfinite(a)
    finite_b = np.isfinite(b)
    if not np.array_equal(finite_a, finite_b):
        moved = int(np.count_nonzero(finite_a != finite_b))
        return Verdict(
            target,
            kind,
            "elementwise",
            f"{moved} cell(s) changed between finite and non-finite",
            None,
            None,
            False,
        )

    if not finite_a.any():
        return Verdict(target, kind, "elementwise", "no finite value", 0.0, 0.0, True)

    left = np.asarray(a[finite_a], dtype=float)
    right = np.asarray(b[finite_b], dtype=float)
    diff = np.abs(left - right)
    max_abs = float(diff.max())
    scale = np.maximum(np.abs(left), np.abs(right))
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(scale > 0, diff / scale, 0.0)
    max_rel = float(np.max(rel))
    # The band is per element, not global: a field whose values span orders of
    # magnitude would otherwise let its small entries move freely under a
    # budget set by its largest one.
    outside = int(np.count_nonzero(diff > atol + rtol * np.abs(right)))
    return Verdict(
        target,
        kind,
        "elementwise",
        f"{a.dtype} {a.shape}, {outside} value(s) past atol + rtol |b|",
        max_abs,
        max_rel,
        outside == 0,
    )


def _walk_zarr(group: Any, prefix: str = "") -> dict[str, Any]:
    """Return every array of a zarr group, keyed by its path inside the store."""
    import zarr

    found: dict[str, Any] = {}
    for name, member in group.members():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(member, zarr.Array):
            found[path] = member
        else:
            found.update(_walk_zarr(member, path))
    return found


def compare_field_stores(a_dir: Path, b_dir: Path, comparison: RunComparison) -> None:
    """Compare the two ``fields.zarr`` stores array by array."""
    import zarr

    store_a, store_b = a_dir / "fields.zarr", b_dir / "fields.zarr"
    for store in (store_a, store_b):
        if not store.exists():
            comparison.errors.append(f"missing field store: {store}")
            return

    arrays_a = _walk_zarr(zarr.open_group(str(store_a), mode="r"))
    arrays_b = _walk_zarr(zarr.open_group(str(store_b), mode="r"))

    for missing in sorted(set(arrays_a) - set(arrays_b)):
        comparison.verdicts.append(
            Verdict(
                f"fields.zarr/{missing}", "structure", "presence", "only in A", None, None, False
            )
        )
    for missing in sorted(set(arrays_b) - set(arrays_a)):
        comparison.verdicts.append(
            Verdict(
                f"fields.zarr/{missing}", "structure", "presence", "only in B", None, None, False
            )
        )

    for name in sorted(set(arrays_a) & set(arrays_b)):
        comparison.verdicts.append(
            compare_arrays(f"fields.zarr/{name}", arrays_a[name][...], arrays_b[name][...])
        )


def _is_volatile(column: str) -> bool:
    """Return True when a column carries an identity or a wall clock."""
    lowered = column.lower()
    if lowered in _VOLATILE_COLUMN_NAMES:
        return True
    return lowered.endswith(("_at", "_hash", "_path", "_uri", "_uris"))


def _drop_volatile_rows(frame: Any, table_name: str) -> Any:
    """Drop the metric rows that record a wall clock rather than a value.

    Scoped to ``metrics.parquet`` on purpose, and to the metric name rather
    than to its variable bucket: ``timeseries.parquet`` carries a ``variable``
    column too, and the ``runtime`` bucket of ``metrics.parquet`` holds the
    water-budget discrepancy next to the solve time.
    """
    if table_name != "metrics.parquet" or "metric" not in frame.columns:
        return frame
    keep = ~frame["metric"].astype(str).str.endswith(_VOLATILE_METRIC_SUFFIXES)
    return frame[keep].reset_index(drop=True)


def compare_tables(a_dir: Path, b_dir: Path, comparison: RunComparison) -> None:
    """Compare the two ``tables.parquet`` directories column by column."""
    import pandas as pd

    tables_a, tables_b = a_dir / "tables.parquet", b_dir / "tables.parquet"
    for tables in (tables_a, tables_b):
        if not tables.exists():
            comparison.errors.append(f"missing tables directory: {tables}")
            return

    names_a = {path.name for path in tables_a.glob("*.parquet")}
    names_b = {path.name for path in tables_b.glob("*.parquet")}
    for missing in sorted(names_a - names_b):
        comparison.verdicts.append(
            Verdict(
                f"tables.parquet/{missing}", "structure", "presence", "only in A", None, None, False
            )
        )
    for missing in sorted(names_b - names_a):
        comparison.verdicts.append(
            Verdict(
                f"tables.parquet/{missing}", "structure", "presence", "only in B", None, None, False
            )
        )

    for name in sorted(names_a & names_b):
        frame_a = _drop_volatile_rows(pd.read_parquet(tables_a / name), name)
        frame_b = _drop_volatile_rows(pd.read_parquet(tables_b / name), name)
        target = f"tables.parquet/{name}"
        if len(frame_a) != len(frame_b):
            comparison.verdicts.append(
                Verdict(
                    target,
                    "table",
                    "presence",
                    f"{len(frame_a)} vs {len(frame_b)} rows",
                    None,
                    None,
                    False,
                )
            )
            continue
        if set(frame_a.columns) != set(frame_b.columns):
            only_a = sorted(set(frame_a.columns) - set(frame_b.columns))
            only_b = sorted(set(frame_b.columns) - set(frame_a.columns))
            comparison.verdicts.append(
                Verdict(
                    target,
                    "table",
                    "presence",
                    f"columns only in A {only_a}, only in B {only_b}",
                    None,
                    None,
                    False,
                )
            )
            continue
        for column in sorted(frame_a.columns):
            if _is_volatile(column):
                comparison.dropped_columns.add(f"{name}:{column}")
                continue
            series_a, series_b = frame_a[column], frame_b[column]
            if series_a.dtype.kind in "fc":
                comparison.verdicts.append(
                    compare_arrays(
                        f"{target}:{column}",
                        series_a.to_numpy(),
                        series_b.to_numpy(),
                        kind="table",
                    )
                )
            else:
                equal = bool(series_a.equals(series_b))
                comparison.verdicts.append(
                    Verdict(
                        f"{target}:{column}",
                        "table",
                        "exact",
                        str(series_a.dtype),
                        None,
                        None,
                        equal,
                    )
                )


def _dig(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return a nested value, or None when any level is absent."""
    node: Any = payload
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def compare_manifests(a_dir: Path, b_dir: Path, comparison: RunComparison) -> None:
    """Compare the stable half of the two ``manifest.json`` seals."""
    path_a, path_b = a_dir / "manifest.json", b_dir / "manifest.json"
    for path in (path_a, path_b):
        if not path.exists():
            comparison.errors.append(f"missing manifest: {path}")
            return

    payload_a = json.loads(path_a.read_text(encoding="utf-8"))
    payload_b = json.loads(path_b.read_text(encoding="utf-8"))

    for keys in _MANIFEST_SCALAR_KEYS:
        target = "manifest.json:" + ".".join(keys)
        value_a, value_b = _dig(payload_a, keys), _dig(payload_b, keys)
        if value_a is None and value_b is None:
            continue
        if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
            gap = _relative_gap(float(value_a), float(value_b))
            comparison.verdicts.append(
                Verdict(
                    target,
                    "manifest",
                    "elementwise",
                    f"{value_a} vs {value_b}",
                    abs(float(value_a) - float(value_b)),
                    gap,
                    gap <= SCALAR_RTOL,
                )
            )
        elif (
            isinstance(value_a, list) and isinstance(value_b, list) and len(value_a) == len(value_b)
        ):
            comparison.verdicts.append(
                compare_arrays(
                    target,
                    np.asarray(value_a, dtype=float),
                    np.asarray(value_b, dtype=float),
                    kind="manifest",
                )
            )
        else:
            comparison.verdicts.append(
                Verdict(
                    target,
                    "manifest",
                    "exact",
                    f"{value_a!r} vs {value_b!r}",
                    None,
                    None,
                    value_a == value_b,
                )
            )

    for keys in _MANIFEST_LIST_KEYS:
        target = "manifest.json:" + ".".join(keys) + " (count)"
        list_a, list_b = _dig(payload_a, keys), _dig(payload_b, keys)
        if not isinstance(list_a, list) or not isinstance(list_b, list):
            continue
        comparison.verdicts.append(
            Verdict(
                target,
                "manifest",
                "exact",
                f"{len(list_a)} vs {len(list_b)}",
                None,
                None,
                len(list_a) == len(list_b),
            )
        )


def compare_run_dirs(run_a: Path, run_b: Path, *, label: str | None = None) -> RunComparison:
    """Compare two finished run directories and return the full verdict set."""
    comparison = RunComparison(
        label=label or f"{run_a.name} vs {run_b.name}", run_a=run_a, run_b=run_b
    )
    for run in (run_a, run_b):
        if not run.is_dir():
            comparison.errors.append(f"not a run directory: {run}")
    if comparison.errors:
        return comparison

    entries_a = {path.name for path in run_a.iterdir() if not path.name.startswith(".")}
    entries_b = {path.name for path in run_b.iterdir() if not path.name.startswith(".")}
    if entries_a != entries_b:
        comparison.verdicts.append(
            Verdict(
                "run directory",
                "structure",
                "presence",
                f"only in A {sorted(entries_a - entries_b)}, only in B {sorted(entries_b - entries_a)}",
                None,
                None,
                False,
            )
        )

    compare_field_stores(run_a, run_b, comparison)
    compare_tables(run_a, run_b, comparison)
    compare_manifests(run_a, run_b, comparison)
    return comparison


def _purge(project_dir: Path, run_name: str, run_dir: Path) -> str | None:
    """Remove one produced run through the catalog, index rows included.

    The two executions land in the project a developer actually works in, so
    leaving their rows behind would mean handing back a catalog that names runs
    which no longer exist. ``hmp catalog delete --now`` is the one path that
    removes both halves.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "catalog",
            "delete",
            run_name,
            "--now",
            "-y",
            "--workspace",
            str(project_dir),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=300,
    )
    if completed.returncode == 0:
        return None
    shutil.rmtree(run_dir, ignore_errors=True)
    return (
        f"could not purge {run_name} through the catalog (code {completed.returncode}); "
        f"the directory was removed, the index still names it. Run `hmp catalog reindex` "
        f"in {project_dir}."
    )


def _label_for(config: Path) -> str:
    """Return the repo-relative label of a project, or its path when outside."""
    try:
        return str(config.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(config)


def _run_once(config: Path, run_name: str, *, timeout: int) -> float:
    """Execute one project through the real CLI and return its wall time."""
    command = [
        sys.executable,
        "-m",
        "hydromodpy",
        "run",
        "--no-lock",
        "--no-display",
        "--set",
        f"simulation.name={run_name}",
        str(config),
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-25:])
        raise RuntimeError(f"hmp run {config} failed with code {completed.returncode}:\n{tail}")
    return elapsed


def execute_twice(config: Path, *, timeout: int = 1800, clean: bool = True) -> RunComparison:
    """Run one project twice under two names and compare the two outputs.

    The two executions share the project workspace on purpose: a project whose
    inputs resolve from its own root cannot be redirected to a scratch
    workspace without losing its DEM, so the comparator runs a project where a
    user would run it and isolates the two executions by run name only.
    """
    config = config.resolve()
    project_dir = config.parent
    stamp = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"
    name_a, name_b = f"cmp_{stamp}_a", f"cmp_{stamp}_b"
    run_a = project_dir / "runs" / name_a
    run_b = project_dir / "runs" / name_b

    comparison = RunComparison(label=_label_for(config), run_a=run_a, run_b=run_b)
    try:
        comparison.seconds_a = _run_once(config, name_a, timeout=timeout)
        comparison.seconds_b = _run_once(config, name_b, timeout=timeout)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        comparison.errors.append(str(exc))
        return comparison

    compared = compare_run_dirs(run_a, run_b, label=comparison.label)
    compared.seconds_a, compared.seconds_b = comparison.seconds_a, comparison.seconds_b
    if clean:
        for name, run in ((name_a, run_a), (name_b, run_b)):
            note = _purge(project_dir, name, run)
            if note:
                compared.notes.append(note)
    return compared


def render_markdown(comparisons: list[RunComparison], *, total_seconds: float) -> str:
    """Render the report a reader acts on: one summary, then one table per pair."""
    lines: list[str] = []
    lines.append("# Double-execution comparison")
    lines.append("")
    lines.append(f"Produced {datetime.now(UTC).isoformat(timespec='seconds')}.")
    lines.append("")
    lines.append(
        f"Bands from `tests/TOLERANCES.md`: float arrays rtol `{FIELD_RTOL:g}` atol `{FIELD_ATOL:g}`, "
        f"signature fallback rtol `{SIGNATURE_RTOL:g}`, manifest scalars rtol `{SCALAR_RTOL:g}`."
    )
    lines.append("")
    lines.append("| Project | Compared | Drifted | Errors | Run A [s] | Run B [s] | Status |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for comparison in comparisons:
        status = "OK" if comparison.ok else "DRIFT"
        lines.append(
            f"| `{comparison.label}` | {len(comparison.verdicts)} | {len(comparison.drifted)} | "
            f"{len(comparison.errors)} | {comparison.seconds_a:.1f} | {comparison.seconds_b:.1f} | {status} |"
        )
    lines.append("")
    lines.append(f"Total wall time: {total_seconds:.1f} s.")
    lines.append("")
    lines.append(
        "The two executions of a project land in that project's own `runs/` directory, "
        "the one a developer works in, and are purged from it through "
        "`hmp catalog delete --now` unless `--keep` is given."
    )
    lines.append("")

    for comparison in comparisons:
        lines.append(f"## `{comparison.label}`")
        lines.append("")
        lines.append(f"- A: `{comparison.run_a}`")
        lines.append(f"- B: `{comparison.run_b}`")
        lines.append("")
        for error in comparison.errors:
            lines.append(f"**Error.** {error}")
            lines.append("")
        for note in comparison.notes:
            lines.append(f"**Note.** {note}")
            lines.append("")
        if comparison.drifted:
            lines.append("### Outside the band")
            lines.append("")
            lines.append("| Target | Kind | Mode | Max abs | Max rel | Detail |")
            lines.append("| --- | --- | --- | ---: | ---: | --- |")
            for verdict in comparison.drifted:
                max_abs = "n/a" if verdict.max_abs is None else f"{verdict.max_abs:.3e}"
                max_rel = "n/a" if verdict.max_rel is None else f"{verdict.max_rel:.3e}"
                lines.append(
                    f"| `{verdict.target}` | {verdict.kind} | {verdict.mode} | {max_abs} | {max_rel} | {verdict.detail} |"
                )
            lines.append("")
        else:
            lines.append("Every compared target is inside its band.")
            lines.append("")
        worst = sorted(
            (v for v in comparison.verdicts if v.max_abs is not None and v.within),
            key=lambda v: v.max_abs or 0.0,
            reverse=True,
        )[:10]
        if worst:
            lines.append("### Largest differences inside the band")
            lines.append("")
            lines.append("| Target | Mode | Max abs | Max rel |")
            lines.append("| --- | --- | ---: | ---: |")
            for verdict in worst:
                max_rel = "n/a" if verdict.max_rel is None else f"{verdict.max_rel:.3e}"
                lines.append(
                    f"| `{verdict.target}` | {verdict.mode} | {verdict.max_abs:.3e} | {max_rel} |"
                )
            lines.append("")
        if comparison.dropped_columns:
            lines.append(
                "Columns dropped as volatile: "
                + ", ".join(f"`{column}`" for column in sorted(comparison.dropped_columns))
                + "."
            )
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one project twice and compare the two run directories within tolerances."
    )
    parser.add_argument(
        "--project",
        action="append",
        type=Path,
        default=[],
        help="project TOML to run twice (repeatable)",
    )
    parser.add_argument("--frozen", action="store_true", help="use the four frozen projects")
    parser.add_argument(
        "--compare",
        nargs=2,
        type=Path,
        metavar=("RUN_A", "RUN_B"),
        help="compare two finished run directories",
    )
    parser.add_argument("--report", type=Path, help="write the Markdown report here")
    parser.add_argument(
        "--json", dest="json_path", type=Path, help="write the machine-readable report here"
    )
    parser.add_argument(
        "--timeout", type=int, default=1800, help="per-execution timeout in seconds"
    )
    parser.add_argument("--keep", action="store_true", help="keep the produced run directories")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    started = time.monotonic()

    comparisons: list[RunComparison] = []
    if args.compare:
        run_a, run_b = args.compare
        if not run_a.is_dir() or not run_b.is_dir():
            print(f"not a run directory: {run_a} or {run_b}", file=sys.stderr)
            return 2
        comparisons.append(compare_run_dirs(run_a, run_b))
    else:
        projects = list(args.project)
        if args.frozen or not projects:
            projects = [REPO_ROOT / name for name in FROZEN_PROJECTS]
        missing = [project for project in projects if not project.is_file()]
        if missing:
            for project in missing:
                print(f"project not found: {project}", file=sys.stderr)
            return 2
        for project in projects:
            comparisons.append(execute_twice(project, timeout=args.timeout, clean=not args.keep))

    report = render_markdown(comparisons, total_seconds=time.monotonic() - started)
    print(report)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps([comparison.as_dict() for comparison in comparisons], indent=2) + "\n",
            encoding="utf-8",
        )

    failed = [comparison for comparison in comparisons if not comparison.ok]
    if failed:
        print(
            f"\nFAIL: {len(failed)} of {len(comparisons)} pair(s) outside their bands.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
