"""B0 reference manifest: reproducibility payload and file hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.calibration.reporting.network_transient import io as _nt_io
from hydromodpy.calibration.reporting.network_transient import state as _state
from hydromodpy.calibration.reporting.network_transient.geometry import _candidate_is_truth
from hydromodpy.calibration.reporting.network_transient.io import (
    NetworkTransientHtmlArtifactReport,
)

_read_json = _nt_io.read_json
_float = _nt_io.coerce_float


def _write_reference_manifest(
    html_report: Path,
    *,
    artifact_report: NetworkTransientHtmlArtifactReport,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
) -> Path:
    manifest = _reference_manifest_payload(
        html_report,
        artifact_report=artifact_report,
        normalization=normalization,
        score_rows=score_rows,
    )
    path = _state.report_facade().REAL_ROOT / "b0_reference_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _reference_manifest_payload(
    html_report: Path,
    *,
    artifact_report: NetworkTransientHtmlArtifactReport,
    normalization: dict[str, Any],
    score_rows: list[dict[str, str]],
) -> dict[str, Any]:
    truth_dir = artifact_report.truth_dir
    score_table = artifact_report.score_table
    metadata = _read_json(truth_dir / "metadata.json") if truth_dir is not None else {}
    completed = [row for row in score_rows if row.get("status") == "completed"]
    failed = [row for row in score_rows if row.get("status") != "completed"]
    best_global = (
        min(completed, key=lambda row: _float(row.get("J"), float("inf"))) if completed else None
    )
    non_target = [row for row in completed if not _candidate_is_truth(row)]
    best_non_target = (
        min(non_target, key=lambda row: _float(row.get("J"), float("inf"))) if non_target else None
    )
    status_counts: dict[str, int] = {}
    for row in score_rows:
        status = str(row.get("status", "") or "").strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    truth_files = {
        "metadata_json": truth_dir / "metadata.json" if truth_dir is not None else None,
        "normalization_json": truth_dir / "normalization.json" if truth_dir is not None else None,
        "steady_network_drain_by_cell_npz": (
            truth_dir / "steady_network_drain_by_cell.npz" if truth_dir is not None else None
        ),
        "steady_network_active_mask_npz": (
            truth_dir / "steady_network_active_mask.npz" if truth_dir is not None else None
        ),
        "transient_q_total_release_csv": (
            truth_dir / "transient_q_total_release.csv" if truth_dir is not None else None
        ),
    }
    contract_version = str(
        normalization.get("contract_version") or "b0_network_steady_discharge_transient.v1"
    )

    return {
        "schema": "hydromodpy.calibration.b0_reference_manifest.v1",
        "contract_version": contract_version,
        "contract": _manifest_contract(
            contract_version,
            normalization=normalization,
            metadata=metadata,
        ),
        "paths": {
            "truth_dir": None if truth_dir is None else str(truth_dir),
            "score_table": None if score_table is None else str(score_table),
            "html_report": str(html_report),
        },
        "truth": {
            "site_id": metadata.get("site_id"),
            "mK_true": metadata.get("mK_true"),
            "Sy_true": metadata.get("Sy_true"),
            "n_cells": metadata.get("n_cells"),
            "n_timesteps": metadata.get("n_timesteps"),
        },
        "score_window": {
            "warmup_periods": normalization.get("warmup_periods"),
            "score_start_index": normalization.get("score_start_index"),
            "score_stop_index": normalization.get("score_stop_index"),
            "scored_periods": normalization.get("scored_periods"),
        },
        "normalization": _manifest_normalization(contract_version, normalization),
        "grid": {
            "rows_total": len(score_rows),
            "completed": len(completed),
            "failed": len(failed),
            "status_counts": status_counts,
        },
        "best_global": _manifest_score_row(best_global),
        "best_non_target": _manifest_score_row(best_non_target),
        "contract_warnings": list(artifact_report.contract_warnings),
        "hashes": {
            "score_table": _sha256_file(score_table),
            **{f"truth.{name}": _sha256_file(path) for name, path in truth_files.items()},
        },
    }


def _manifest_score_row(row: dict[str, str] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "candidate_id",
        "mK",
        "Sy",
        "status",
        "J",
        "C_reseau_phys",
        "C_debit_phys",
        "C_reseau_naturel",
        "C_debit_obs",
        "network_map_source",
        "error",
    )
    out: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if key in {
            "mK",
            "Sy",
            "J",
            "C_reseau_phys",
            "C_debit_phys",
            "C_reseau_naturel",
            "C_debit_obs",
        }:
            numeric = _float(value)
            out[key] = numeric if np.isfinite(numeric) else None
        elif value not in (None, ""):
            out[key] = value
    return out


def _manifest_normalization(
    contract_version: str,
    normalization: dict[str, Any],
) -> dict[str, Any]:
    if contract_version.startswith("natural_"):
        keys = (
            "Q_ref_steady",
            "Qbar_ref",
            "L_ref",
            "d_tol",
            "tau_network",
            "eta_dist",
            "network_distance_metric",
            "discharge_metric",
            "alpha_Q",
            "nse_log_epsilon",
            "w_reseau",
            "w_debit",
        )
    else:
        keys = (
            "Q_ref_steady",
            "Qbar_ref",
            "L_ref",
            "d_tol",
            "tau_network",
            "eta_flux",
            "eta_dist",
            "eta_len",
            "network_distance_metric",
            "discharge_metric",
            "alpha_Q",
            "nse_log_epsilon",
            "w_reseau",
            "w_debit",
        )
    return {key: normalization.get(key) for key in keys}


def _manifest_contract(
    contract_version: str,
    *,
    normalization: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    w_network = _float(normalization.get("w_reseau"), 0.5)
    w_discharge = _float(normalization.get("w_debit"), 0.5)
    if contract_version.startswith("natural_") or metadata.get("package_type") == (
        "natural_observation_package"
    ):
        objective = f"{w_network:g}*C_reseau_naturel + {w_discharge:g}*C_debit_obs"
        network_observable = metadata.get(
            "network_observable",
            "observed_hydrography_presence_vs_steady_outflow_support",
        )
        discharge_observable = metadata.get("discharge_observable", "observed_streamflow")
    else:
        objective = f"{w_network:g}*C_reseau_phys + {w_discharge:g}*C_debit_phys"
        network_observable = "steady_outflow_drain"
        discharge_observable = "transient_Q_total_release"
    return {
        "network_observable": network_observable,
        "discharge_observable": discharge_observable,
        "objective": objective,
        "failure_policy": {
            "reporting": "failed candidates keep status and NaN objective; they are excluded from ranking",
            "future_optimizer": "return pruned/failed or a finite penalty outside the report ranking path",
        },
    }


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
