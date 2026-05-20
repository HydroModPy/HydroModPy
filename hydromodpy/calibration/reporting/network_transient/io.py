"""CSV/JSON/TOML readers, artifact inspection and small parsing helpers."""

from __future__ import annotations

import csv
import json
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class NetworkTransientHtmlArtifactReport:
    """Resolved artifact contract for one network/transient HTML report."""

    real_root: Path
    truth_dir: Path | None
    score_table: Path | None
    available: tuple[str, ...]
    required_missing: tuple[str, ...]
    optional_missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.required_missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "hydromodpy.calibration.network_transient_html_artifacts.v1",
            "ok": self.ok,
            "real_root": str(self.real_root),
            "truth_dir": None if self.truth_dir is None else str(self.truth_dir),
            "score_table": None if self.score_table is None else str(self.score_table),
            "available": list(self.available),
            "required_missing": list(self.required_missing),
            "optional_missing": list(self.optional_missing),
        }


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV as a list of OrderedDict rows; empty when missing."""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON dict; empty when missing."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML dict; empty when missing."""
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def first_existing(paths: tuple[Path, ...]) -> Path | None:
    """Return the first existing path, or None."""
    for path in paths:
        if path.exists():
            return path
    return None


def first_score_table(paths: tuple[Path, ...]) -> Path | None:
    """Return the first score table with at least one completed row."""
    for path in paths:
        if not path.exists():
            continue
        rows = read_csv(path)
        if any(row.get("status") == "completed" for row in rows):
            return path
    return first_existing(paths)


def read_truth_discharge(path: Path) -> list[float]:
    """Read the synthetic truth Q_total_release column from a CSV."""
    rows = read_csv(path)
    return [coerce_float(row.get("q_total_release")) for row in rows]


def coerce_float(value: Any, default: float = float("nan")) -> float:
    """Coerce a value to float; return ``default`` on TypeError/ValueError."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_float(value: Any, digits: int = 4) -> str:
    """Format a value as a short fixed-or-scientific string; empty when NaN."""
    val = coerce_float(value)
    if not np.isfinite(val):
        return ""
    if abs(val) >= 1e4 or (abs(val) < 1e-3 and val != 0.0):
        return f"{val:.{digits}e}"
    return f"{val:.{digits}f}"


def as_int_str(value: Any) -> str:
    """Format an integer-like value with thousands separators; '-' when missing."""
    if value in (None, 0):
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def default_truth_packages(real_root: Path) -> tuple[Path, ...]:
    """Return the default truth-package paths under one real_runs root."""
    return (
        real_root / "site_01_truth_package_mK_0p65",
        real_root / "site_01_truth_package",
    )


def default_score_tables(real_root: Path) -> tuple[Path, ...]:
    """Return the default score-table paths under one real_runs root."""
    return (
        real_root / "site_01_parameter_grid_scores_mK_0p65.csv",
        real_root / "site_01_candidate_scores_mK_0p65.csv",
        real_root / "site_01_candidate_scores.csv",
        real_root / "site_01_parameter_grid_light_scores_mK_0p65.csv",
    )


def default_path_base(real_root: Path) -> Path:
    """Infer the project root from the real_runs directory."""
    if real_root.name == "real_runs" and real_root.parent.name == "outputs":
        return real_root.parent.parent.resolve()
    return real_root.resolve()


def inspect_network_transient_html_artifacts(
    *,
    real_root: Path,
    source_transient_config: Path,
    reference_run_root: Path | None = None,
    steady_summary_csv: Path | None = None,
    truth_packages: Iterable[Path] | None = None,
    score_tables: Iterable[Path] | None = None,
) -> NetworkTransientHtmlArtifactReport:
    """Inspect whether the standard network/transient HTML artifacts are present."""
    resolved_real_root = Path(real_root).resolve()
    truth_candidates = tuple(
        Path(path).resolve()
        for path in (truth_packages or default_truth_packages(resolved_real_root))
    )
    score_candidates = tuple(
        Path(path).resolve() for path in (score_tables or default_score_tables(resolved_real_root))
    )
    truth_dir = first_existing(truth_candidates)
    score_table = first_score_table(score_candidates)
    reference_root = (
        Path(reference_run_root).resolve()
        if reference_run_root is not None
        else resolved_real_root / "candidate_mK_0p65_Sy_0p05_steady_mf6"
    )
    steady_csv = (
        Path(steady_summary_csv).resolve()
        if steady_summary_csv is not None
        else resolved_real_root / "steady_mK_network_extent_summary.csv"
    )

    available: list[str] = []
    required_missing: list[str] = []
    optional_missing: list[str] = []

    def check(name: str, path: Path | None, *, required: bool) -> None:
        if path is not None and path.exists():
            available.append(name)
            return
        (required_missing if required else optional_missing).append(name)

    check("truth_package", truth_dir, required=True)
    if truth_dir is not None:
        check("truth.metadata_json", truth_dir / "metadata.json", required=True)
        check("truth.normalization_json", truth_dir / "normalization.json", required=True)
        check(
            "truth.transient_q_total_release_csv",
            truth_dir / "transient_q_total_release.csv",
            required=True,
        )
        check(
            "truth.steady_network_drain_by_cell_npz",
            truth_dir / "steady_network_drain_by_cell.npz",
            required=False,
        )
        check(
            "truth.steady_network_active_mask_npz",
            truth_dir / "steady_network_active_mask.npz",
            required=False,
        )
    check("score_table", score_table, required=True)
    if score_table is not None and score_table.exists():
        rows = read_csv(score_table)
        if any(row.get("status") == "completed" for row in rows):
            available.append("score_table.completed_rows")
        else:
            required_missing.append("score_table.completed_rows")
    check("source_transient_config", Path(source_transient_config).resolve(), required=False)
    check("reference_run_root", reference_root, required=False)
    check("steady_summary_csv", steady_csv, required=False)

    return NetworkTransientHtmlArtifactReport(
        real_root=resolved_real_root,
        truth_dir=truth_dir,
        score_table=score_table,
        available=tuple(available),
        required_missing=tuple(required_missing),
        optional_missing=tuple(optional_missing),
    )
