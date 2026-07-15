"""Run a lightweight real MF6 B0 parameter grid.

This driver reuses the calibration trial primitive instead of launching the
full HydroModPy CLI for every candidate.  It keeps the B0 prototype local:

- prepare one steady context and one transient context;
- fork those contexts for every candidate;
- post-process only ``outflow_drain`` in RAM-facing scratch files;
- write compact score/time-series artifacts;
- leave full catalog promotion to the existing persistent driver.
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from hydromodpy.calibration.observations.network_transient_truth import (  # noqa: E402
    q_total_release_from_drain_by_cell,
    score_network_transient_candidate,
)
from hydromodpy.calibration.runners.materialize import write_overlay_toml  # noqa: E402
from hydromodpy.calibration.runners.trial import prepare_trials, run_trial_light  # noqa: E402
from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider  # noqa: E402
from hydromodpy.results.catalog import Catalog  # noqa: E402
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions  # noqa: E402

from run_real_parameter_grid import (  # noqa: E402
    CONFIG_ROOT,
    GRID_SCORES_CSV,
    GRID_SCORES_JSON,
    REAL_ROOT,
    SOURCE_K_CSV,
    SOURCE_TRANSIENT_CONFIG,
    TRUTH_DIR,
)


LIGHT_ROOT = REAL_ROOT / "light_grid"
LIGHT_STEADY_DIR = LIGHT_ROOT / "steady_drain"
LIGHT_TRANSIENT_DIR = LIGHT_ROOT / "transient_q"
LIGHT_SCORES_CSV = REAL_ROOT / "site_01_parameter_grid_light_scores_mK_0p65.csv"
LIGHT_SCORES_JSON = REAL_ROOT / "site_01_parameter_grid_light_scores_mK_0p65.json"
LIGHT_TIMINGS_JSON = REAL_ROOT / "site_01_parameter_grid_light_timings_mK_0p65.json"
LIGHT_STEADY_CONFIG = CONFIG_ROOT / "light_steady_base.toml"
LIGHT_TRANSIENT_CONFIG = CONFIG_ROOT / "light_transient_base.toml"
TARGET_MK = 0.65
TARGET_SY = 0.05
REFERENCE_MESH_ROOT: Path | None = None
K_MODE = "csv"
BASE_K_VALUE = 1.0
BASE_K_UNIT = "m/s"
STEADY_IC_TYPE = "top"
STEADY_IC_OFFSET_M = 1.0
NETWORK_MAP_SOURCE = "steady"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-id",
        default="site_01",
        help="Site identifier used to name output artifacts.",
    )
    parser.add_argument(
        "--source-transient-config",
        type=Path,
        default=SOURCE_TRANSIENT_CONFIG,
        help="Simulation TOML used as the transient source configuration.",
    )
    parser.add_argument(
        "--source-k-csv",
        type=Path,
        default=SOURCE_K_CSV,
        help="Base geology K CSV to multiply by mK when the source config uses CSV K.",
    )
    parser.add_argument(
        "--k-mode",
        choices=["auto", "csv", "homogeneous"],
        default="auto",
        help="How mK is applied. Auto follows the source config K field kind.",
    )
    parser.add_argument(
        "--real-root",
        type=Path,
        default=REAL_ROOT,
        help="Root directory for truth, scores and lightweight scratch artifacts.",
    )
    parser.add_argument(
        "--truth-dir",
        type=Path,
        default=None,
        help="Truth package directory. Defaults to <real-root>/<site>_truth_package_mK_<target>.",
    )
    parser.add_argument(
        "--target-mk",
        type=float,
        default=TARGET_MK,
        help="mK value marked as the synthetic truth in candidate identifiers.",
    )
    parser.add_argument(
        "--target-sy",
        type=float,
        default=TARGET_SY,
        help="Sy value marked as the synthetic truth in candidate identifiers.",
    )
    parser.add_argument(
        "--light-root",
        type=Path,
        default=None,
        help="Optional lightweight scratch root. Defaults to <real-root>/light_grid for site_01 and <real-root>/<site>_light_grid otherwise.",
    )
    parser.add_argument(
        "--reference-mesh-root",
        type=Path,
        default=None,
        help="Optional completed run/workspace whose mesh/mesh_catchment_bundle should be reused.",
    )
    parser.add_argument(
        "--output-stem",
        default=None,
        help="Optional score artifact stem, without .csv/.json extension.",
    )
    parser.add_argument(
        "--mk-values",
        nargs="+",
        type=float,
        default=_default_dense_mk_values(),
        help="mK grid values.",
    )
    parser.add_argument(
        "--sy-values",
        nargs="+",
        type=float,
        default=_default_dense_sy_values(),
        help="Sy grid values.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Stop after this many transient candidate evaluations.",
    )
    parser.add_argument(
        "--reuse-light-artifacts",
        action="store_true",
        help="Reuse compact lightweight NPZ/CSV artifacts when present.",
    )
    parser.add_argument(
        "--keep-solver-files",
        action="store_true",
        help="Keep raw lightweight solver scratch folders after extracting outflow_drain.",
    )
    parser.add_argument(
        "--force-light-steady",
        action="store_true",
        help=(
            "Do not reuse existing persistent steady catalogs; try to run steady in "
            "lightweight mode instead."
        ),
    )
    parser.add_argument(
        "--steady-ic",
        choices=["top", "top_offset", "bottom"],
        default=STEADY_IC_TYPE,
        help="Initial head strategy used by the lightweight steady solve.",
    )
    parser.add_argument(
        "--steady-ic-offset-m",
        type=float,
        default=STEADY_IC_OFFSET_M,
        help="Offset below top surface, in metres, when --steady-ic=top_offset.",
    )
    parser.add_argument(
        "--also-write-main-score",
        action="store_true",
        help=(
            "Also copy the lightweight score table to the main grid-score path used by "
            "the HTML report."
        ),
    )
    parser.add_argument(
        "--network-map-source",
        choices=["steady", "transient_last", "transient_mean"],
        default=NETWORK_MAP_SOURCE,
        help=(
            "Drainage map used for the spatial objective. The canonical B0 contract uses "
            "'steady'; transient_* is retained only for exploratory diagnostics."
        ),
    )
    parser.add_argument(
        "--extract-target-artifacts-only",
        action="store_true",
        help=(
            "Run the target mK/Sy transient once and write compact q/map artifacts "
            "without requiring an existing truth package."
        ),
    )
    args = parser.parse_args(argv)
    _configure_from_args(args)

    _ensure_dirs()

    timings: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    steady_ctx = None
    steady_override_paths = _k_override_paths()
    if args.force_light_steady:
        _write_steady_light_base_config()
        steady_ctx = _prepare_context(
            LIGHT_STEADY_CONFIG,
            override_paths=steady_override_paths,
            label="steady",
            timings=timings,
        )
    _write_transient_light_base_config()
    transient_ctx = _prepare_context(
        LIGHT_TRANSIENT_CONFIG,
        override_paths={**_k_override_paths(), "Sy": "flow.param.Sy.field.value"},
        label="transient",
        timings=timings,
    )

    if args.extract_target_artifacts_only:
        if NETWORK_MAP_SOURCE == "steady":
            _steady_for_mk(
                steady_ctx,
                TARGET_MK,
                timings=timings,
                reuse=args.reuse_light_artifacts,
                keep_solver_files=args.keep_solver_files,
                force_light=args.force_light_steady,
            )
        status, error, _, _ = _run_transient_pair(
            transient_ctx,
            TARGET_MK,
            TARGET_SY,
            timings=timings,
            reuse=args.reuse_light_artifacts,
            keep_solver_files=args.keep_solver_files,
        )
        timings.append(
            {
                "kind": "total",
                "seconds": time.perf_counter() - t0,
                "n_rows": 0,
            }
        )
        LIGHT_TIMINGS_JSON.write_text(
            json.dumps(timings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if status != "completed":
            print(f"Target artifact extraction failed: {error}")
            return 1
        print(f"Wrote target q artifact: {_transient_q_artifact(TARGET_MK, TARGET_SY)}")
        if NETWORK_MAP_SOURCE != "steady":
            print(
                "Wrote target network map artifact: "
                f"{_transient_network_artifact(TARGET_MK, TARGET_SY)}"
            )
        return 0

    rows: list[dict[str, Any]] = []
    steady_cache: dict[float, np.ndarray] = {}
    evaluated = 0
    for mk in args.mk_values:
        steady_drain = None
        if NETWORK_MAP_SOURCE == "steady":
            steady_drain = _steady_for_mk(
                steady_ctx,
                mk,
                timings=timings,
                reuse=args.reuse_light_artifacts,
                keep_solver_files=args.keep_solver_files,
                force_light=args.force_light_steady,
            )
        if steady_drain is not None:
            steady_cache[mk] = steady_drain

        for sy in args.sy_values:
            if args.max_candidates is not None and evaluated >= args.max_candidates:
                break
            row = _score_pair(
                transient_ctx,
                mk,
                sy,
                steady_cache.get(mk),
                timings=timings,
                reuse=args.reuse_light_artifacts,
                keep_solver_files=args.keep_solver_files,
            )
            rows.append(row)
            evaluated += 1
        if args.max_candidates is not None and evaluated >= args.max_candidates:
            break

    _write_score_tables(rows, also_main=args.also_write_main_score)
    timings.append(
        {
            "kind": "total",
            "seconds": time.perf_counter() - t0,
            "n_rows": len(rows),
        }
    )
    LIGHT_TIMINGS_JSON.write_text(
        json.dumps(timings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    completed = [row for row in rows if row.get("status") == "completed"]
    print(f"Wrote lightweight scores: {LIGHT_SCORES_CSV}")
    print(f"Completed: {len(completed)} / {len(rows)}")
    if completed:
        best = min(completed, key=lambda row: float(row.get("J", float("inf"))))
        print(
            "Best: "
            f"{best['candidate_id']} J={float(best['J']):.12g} "
            f"mK={float(best['mK']):.6g} Sy={float(best['Sy']):.6g}"
        )
    return 0


def _configure_from_args(args: argparse.Namespace) -> None:
    global CONFIG_ROOT
    global GRID_SCORES_CSV
    global GRID_SCORES_JSON
    global LIGHT_ROOT
    global LIGHT_SCORES_CSV
    global LIGHT_SCORES_JSON
    global LIGHT_STEADY_CONFIG
    global LIGHT_STEADY_DIR
    global LIGHT_TIMINGS_JSON
    global LIGHT_TRANSIENT_CONFIG
    global LIGHT_TRANSIENT_DIR
    global K_MODE
    global NETWORK_MAP_SOURCE
    global REAL_ROOT
    global REFERENCE_MESH_ROOT
    global BASE_K_UNIT
    global BASE_K_VALUE
    global SOURCE_K_CSV
    global SOURCE_TRANSIENT_CONFIG
    global STEADY_IC_OFFSET_M
    global STEADY_IC_TYPE
    global TARGET_MK
    global TARGET_SY
    global TRUTH_DIR

    site_id = str(args.site_id).strip() or "site_01"
    TARGET_MK = float(args.target_mk)
    TARGET_SY = float(args.target_sy)
    STEADY_IC_TYPE = str(args.steady_ic).strip().lower()
    STEADY_IC_OFFSET_M = float(args.steady_ic_offset_m)
    NETWORK_MAP_SOURCE = str(args.network_map_source).strip().lower()
    SOURCE_K_CSV = Path(args.source_k_csv)
    REAL_ROOT = Path(args.real_root)
    CONFIG_ROOT = REAL_ROOT / "configs"
    target_tag = _value_tag(TARGET_MK)
    SOURCE_TRANSIENT_CONFIG = _normalized_source_config(
        Path(args.source_transient_config),
        site_id=site_id,
    )
    K_MODE, BASE_K_VALUE, BASE_K_UNIT = _resolve_k_mode(
        SOURCE_TRANSIENT_CONFIG,
        requested=str(args.k_mode),
    )
    TRUTH_DIR = (
        Path(args.truth_dir)
        if args.truth_dir is not None
        else REAL_ROOT / f"{site_id}_truth_package_mK_{target_tag}"
    )
    light_root_default = "light_grid" if site_id == "site_01" else f"{site_id}_light_grid"
    LIGHT_ROOT = (
        Path(args.light_root) if args.light_root is not None else REAL_ROOT / light_root_default
    )
    LIGHT_STEADY_DIR = LIGHT_ROOT / "steady_drain"
    LIGHT_TRANSIENT_DIR = LIGHT_ROOT / "transient_q"
    stem = args.output_stem or f"{site_id}_parameter_grid_light_scores_mK_{target_tag}"
    LIGHT_SCORES_CSV = REAL_ROOT / f"{stem}.csv"
    LIGHT_SCORES_JSON = REAL_ROOT / f"{stem}.json"
    timing_stem = stem.replace("_scores_", "_timings_")
    if timing_stem == stem:
        timing_stem = f"{stem}_timings"
    LIGHT_TIMINGS_JSON = REAL_ROOT / f"{timing_stem}.json"
    LIGHT_STEADY_CONFIG = CONFIG_ROOT / f"{site_id}_light_steady_base.toml"
    LIGHT_TRANSIENT_CONFIG = CONFIG_ROOT / f"{site_id}_light_transient_base.toml"
    GRID_SCORES_CSV = REAL_ROOT / f"{site_id}_parameter_grid_scores_mK_{target_tag}.csv"
    GRID_SCORES_JSON = REAL_ROOT / f"{site_id}_parameter_grid_scores_mK_{target_tag}.json"
    REFERENCE_MESH_ROOT = Path(args.reference_mesh_root) if args.reference_mesh_root else None


def _normalized_source_config(source: Path, *, site_id: str) -> Path:
    """Return a source TOML path compatible with the current config schema."""

    text = source.read_text(encoding="utf-8")
    normalized = (
        text.replace('provider = "geology"', 'kind = "geology"')
        .replace('type = "constant_thickness"', 'kind = "constant_thickness"')
        .replace('type = "flat_substratum"', 'kind = "flat_substratum"')
    )
    if normalized == text:
        return source

    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    target = CONFIG_ROOT / f"{site_id}_source_current_schema.toml"
    target.write_text(normalized, encoding="utf-8")
    return target


def _resolve_k_mode(source: Path, *, requested: str) -> tuple[str, float, str]:
    payload = tomllib.loads(source.read_text(encoding="utf-8"))
    field = payload.get("flow", {}).get("param", {}).get("K", {}).get("field", {})
    source_kind = str(field.get("kind", "")).strip()
    mode = source_kind if requested == "auto" else requested
    if mode not in {"csv", "heterogeneous", "homogeneous"}:
        mode = "csv"
    if mode == "heterogeneous":
        mode = "csv"
    value = str(field.get("value", "1.0 m/s")).strip()
    parts = value.split(maxsplit=1)
    try:
        base_value = float(parts[0])
    except (IndexError, ValueError):
        base_value = 1.0
    unit = parts[1] if len(parts) > 1 else str(field.get("unit", "m/s"))
    return mode, base_value, unit


def _ensure_dirs() -> None:
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    LIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    LIGHT_STEADY_DIR.mkdir(parents=True, exist_ok=True)
    LIGHT_TRANSIENT_DIR.mkdir(parents=True, exist_ok=True)


def _write_steady_light_base_config() -> Path:
    cfg = get_root_config_provider().from_toml(SOURCE_TRANSIENT_CONFIG)
    payload = cfg.model_dump(mode="json", exclude_none=True)
    recharge_values = _source_recharge_values_mm_per_day(payload)
    steady_recharge = float(np.mean(recharge_values)) if recharge_values.size else 0.0
    payload["simulation"]["name"] = "b0_light_steady_mf6"
    payload["simulation"]["run_id"] = "b0_light_steady_mf6"
    payload["workspace"]["project_root"] = str((LIGHT_ROOT / "steady_workspace").resolve())
    payload["simulation"]["time"] = {
        "start_datetime": "2000-09-01T00:00:00",
        "end_datetime": "2000-09-30T00:00:00",
        "step_value": "1 month",
        "coverage_policy": "warn",
    }
    payload["data"]["recharge"] = {
        "date_start": "2000-09-01",
        "date_end": "2000-09-30",
        "sources": [
            {
                "source": "synthetic",
                "freq": "MS",
                "start_date": "2000-09-01",
                "periods": 1,
                "values": [steady_recharge],
                "runoff_ratio": 0.0,
            }
        ],
    }
    payload["flow"]["flow_regime"] = "steady"
    payload["flow"]["active_sinks_sources"] = ["recharge"]
    payload["flow"]["active_bc"] = ["drainage"]
    payload["flow"]["ic"] = _steady_ic_payload()
    _set_payload_recharge_values(payload, steady_recharge)
    _set_payload_k_field(payload)
    payload["flow"]["param"]["Sy"]["field"]["value"] = "0.05 -"
    mesh_hydraulic = payload.get("mesh_catchment", {}).get("hydraulic_properties", {})
    if isinstance(mesh_hydraulic, dict):
        conductivity = mesh_hydraulic.get("conductivity")
        if isinstance(conductivity, dict) and "values_csv_file" in conductivity:
            conductivity["values_csv_file"] = str(SOURCE_K_CSV.resolve())
    mesh_input = _reference_mesh_input()
    if mesh_input:
        payload.pop("mesh_catchment", None)
        payload["mesh_input"] = mesh_input
    _patch_mesh_input_paths(payload)
    payload.setdefault("display", {})["enabled"] = False
    write_overlay_toml(LIGHT_STEADY_CONFIG, payload)
    return LIGHT_STEADY_CONFIG


def _steady_ic_payload() -> dict[str, str]:
    if STEADY_IC_TYPE == "top_offset":
        return {"type": "top_offset", "value": f"{STEADY_IC_OFFSET_M:.16g} m"}
    return {"type": STEADY_IC_TYPE}


def _write_transient_light_base_config() -> Path:
    cfg = get_root_config_provider().from_toml(SOURCE_TRANSIENT_CONFIG)
    payload = cfg.model_dump(mode="json", exclude_none=True)
    recharge_values = _source_recharge_values_mm_per_day(payload)
    payload["simulation"]["name"] = "b0_light_transient_mf6"
    payload["simulation"]["run_id"] = "b0_light_transient_mf6"
    payload["workspace"]["project_root"] = str((LIGHT_ROOT / "workspace").resolve())
    payload.setdefault("display", {})["enabled"] = False
    if recharge_values.size:
        _set_payload_recharge_values(payload, recharge_values.tolist())
    _set_payload_k_field(payload)
    payload["flow"]["param"]["Sy"]["field"]["value"] = "0.05 -"
    mesh_input = _reference_mesh_input()
    if mesh_input:
        payload.pop("mesh_catchment", None)
        payload["mesh_input"] = mesh_input
    mesh_hydraulic = payload.get("mesh_catchment", {}).get("hydraulic_properties", {})
    if isinstance(mesh_hydraulic, dict):
        conductivity = mesh_hydraulic.get("conductivity")
        if isinstance(conductivity, dict) and "values_csv_file" in conductivity:
            conductivity["values_csv_file"] = str(SOURCE_K_CSV.resolve())
    _patch_mesh_input_paths(payload)
    write_overlay_toml(LIGHT_TRANSIENT_CONFIG, payload)
    return LIGHT_TRANSIENT_CONFIG


def _source_recharge_values_mm_per_day(payload: dict[str, Any]) -> np.ndarray:
    recharge = payload.get("data", {}).get("recharge", {})
    sources = recharge.get("sources", []) if isinstance(recharge, dict) else []
    for source in sources:
        if not isinstance(source, dict) or "values" not in source:
            continue
        raw_values = np.asarray(source.get("values", []), dtype=float).reshape(-1)
        if raw_values.size == 0:
            continue
        runoff_ratio = float(source.get("runoff_ratio", 0.0) or 0.0)
        return raw_values * max(0.0, 1.0 - runoff_ratio)
    return np.asarray([], dtype=float)


def _set_payload_recharge_values(payload: dict[str, Any], values: float | list[float]) -> None:
    flow = payload.setdefault("flow", {})
    flow.setdefault("active_sinks_sources", ["recharge"])
    if "recharge" not in flow["active_sinks_sources"]:
        flow["active_sinks_sources"].append("recharge")
    sinks_sources = flow.setdefault("sinks_sources", {})
    recharge = sinks_sources.setdefault("recharge", {})
    recharge["values"] = values
    recharge["units"] = "mm/day"
    recharge.setdefault("first_clim", "mean")
    recharge.setdefault("negative_to_evt", True)


def _set_payload_k_field(payload: dict[str, Any]) -> None:
    field = payload["flow"]["param"]["K"]["field"]
    if K_MODE == "homogeneous":
        field.clear()
        field.update(
            {
                "id": "K",
                "kind": "homogeneous",
                "unit": BASE_K_UNIT,
                "value": _k_value_text(1.0),
            }
        )
        return
    field.clear()
    field.update(
        {
            "id": "K",
            "kind": "heterogeneous",
            "unit": "m/s",
            "values_source": "csv",
            "values_csv_file": str(SOURCE_K_CSV.resolve()),
            "csv_key_column": "zone_key",
            "csv_value_column": "K_value",
            "field_spatial_id": "field_geology",
        }
    )


def _reference_mesh_input() -> dict[str, str]:
    root = REFERENCE_MESH_ROOT or _steady_root(TARGET_MK)
    summary_path = root / "mesh" / "mesh_catchment_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
        mesh_path = _normalize_existing_path(summary.get("output_mesh"))
        bundle_dir = _normalize_existing_path(summary.get("output_exchange_bundle_dir"))
        if bundle_dir == "":
            bundle_dir = str((root / "mesh" / "mesh_catchment_bundle").resolve())
        if mesh_path == "":
            mesh_path = str((root / "mesh" / "mesh_catchment.msh").resolve())
        return {"mesh_path": mesh_path, "bundle_dir": bundle_dir}
    bundle_dir = root / "mesh" / "mesh_catchment_bundle"
    mesh_path = root / "mesh" / "mesh_catchment.msh"
    if bundle_dir.is_dir() and mesh_path.is_file():
        return {"mesh_path": str(mesh_path.resolve()), "bundle_dir": str(bundle_dir.resolve())}
    return {}


def _normalize_existing_path(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("/mnt/c/"):
        if not Path("/mnt/c").exists():
            text = "C:/" + text[len("/mnt/c/") :]
    if text == "":
        return ""
    return str(Path(text).resolve())


def _patch_mesh_input_paths(payload: dict[str, Any]) -> None:
    mesh = payload.get("mesh_catchment")
    if not isinstance(mesh, dict):
        return
    geology = mesh.get("geology")
    if not isinstance(geology, dict):
        return
    source = geology.get("source")
    if not isinstance(source, dict):
        return
    if "path" in source:
        source["path"] = str((REPO_ROOT / "examples" / "data" / "geology" / "GEO1M.shp").resolve())
    if "reference_raster_path" in source:
        source["reference_raster_path"] = str(
            (REPO_ROOT / "examples" / "data" / "dem" / "DEM_armorican_massif.tif").resolve()
        )


def _prepare_context(
    cfg_path: Path,
    *,
    override_paths: dict[str, str],
    label: str,
    timings: list[dict[str, Any]],
):
    start = time.perf_counter()
    ctx = prepare_trials(cfg_path, override_paths=override_paths)
    elapsed = time.perf_counter() - start
    timings.append(
        {
            "kind": "prepare",
            "label": label,
            "seconds": elapsed,
            "earliest_step": int(ctx.earliest),
        }
    )
    print(f"[prepare] {label}: earliest={ctx.earliest} in {elapsed:.1f} s")
    return ctx


def _steady_for_mk(
    steady_ctx,
    mk: float,
    *,
    timings: list[dict[str, Any]],
    reuse: bool,
    keep_solver_files: bool,
    force_light: bool,
) -> np.ndarray | None:
    artifact = _steady_artifact(mk)
    if reuse and artifact.is_file():
        return np.load(artifact)["outflow_drain"]
    if not force_light:
        catalog_drain = _steady_from_persistent_catalog(mk)
        if catalog_drain is not None:
            np.savez_compressed(artifact, outflow_drain=catalog_drain)
            timings.append(
                {
                    "kind": "steady",
                    "tag": _mk_tag(mk),
                    "status": "reused_catalog",
                    "seconds": 0.0,
                    "error": "",
                }
            )
            print(f"[steady] {_mk_tag(mk)} reused persistent catalog")
            return catalog_drain
    if steady_ctx is None:
        return None

    captured: dict[str, np.ndarray] = {}

    def metric_fn(ctx, *, objective: str, variable: str):
        del objective, variable
        drain = _extract_outflow_drain_stack(ctx, keep_solver_files=keep_solver_files)[-1]
        captured["outflow_drain"] = drain
        return 0.0, {"n_cells": float(drain.size), "q_total_m3_s": float(np.sum(drain))}

    start = time.perf_counter()
    result = run_trial_light(
        steady_ctx,
        _k_trial_params(mk),
        objective="b0_steady",
        variable="outflow_drain",
        metric_fn=metric_fn,
    )
    elapsed = time.perf_counter() - start
    timings.append(
        {
            "kind": "steady",
            "tag": _mk_tag(mk),
            "status": result.status,
            "seconds": elapsed,
            "error": result.error or "",
        }
    )
    print(f"[steady] {_mk_tag(mk)} {result.status} in {elapsed:.1f} s")
    if result.status != "completed":
        return None
    drain = captured["outflow_drain"]
    np.savez_compressed(artifact, outflow_drain=drain)
    return drain


def _steady_from_persistent_catalog(mk: float) -> np.ndarray | None:
    root = _steady_root(mk)
    if not root.is_dir():
        return None
    try:
        with Catalog(root) as catalog:
            sims = catalog.simulations
            if sims.empty:
                return None
            sim_id = str(sims.iloc[0]["sim_id"])
            run = catalog[sim_id]
            return np.asarray(run.field("outflow_drain", timestep=-1), dtype=float).reshape(-1)
    except Exception:
        return None


def _score_pair(
    transient_ctx,
    mk: float,
    sy: float,
    steady_drain: np.ndarray | None,
    *,
    timings: list[dict[str, Any]],
    reuse: bool,
    keep_solver_files: bool,
) -> dict[str, Any]:
    cid = _candidate_id(mk, sy)
    row: dict[str, Any] = {
        "candidate_id": cid,
        "mK": float(mk),
        "Sy": float(sy),
        "lightweight": True,
        "network_map_source": NETWORK_MAP_SOURCE,
        "steady_drain_npz": (
            _relative_or_abs(_steady_artifact(mk)).as_posix()
            if NETWORK_MAP_SOURCE == "steady"
            else ""
        ),
        "transient_network_npz": _relative_or_abs(_transient_network_artifact(mk, sy)).as_posix(),
        "transient_q_csv": _relative_or_abs(_transient_q_artifact(mk, sy)).as_posix(),
    }
    if NETWORK_MAP_SOURCE == "steady" and steady_drain is None:
        row.update({"status": "failed", "objective": np.nan, "error": "steady run failed"})
        return row

    status, error, q_total, transient_network_map = _run_transient_pair(
        transient_ctx,
        mk,
        sy,
        timings=timings,
        reuse=reuse,
        keep_solver_files=keep_solver_files,
    )
    if status != "completed" or q_total is None:
        row.update({"status": status, "objective": np.nan, "error": error})
        return row
    if NETWORK_MAP_SOURCE == "steady":
        network_map = steady_drain
    else:
        network_map = transient_network_map
    if network_map is None:
        row.update({"status": "failed", "objective": np.nan, "error": "network map missing"})
        return row
    row.update(_score_arrays(network_map, q_total))
    return row


def _run_transient_pair(
    transient_ctx,
    mk: float,
    sy: float,
    *,
    timings: list[dict[str, Any]],
    reuse: bool,
    keep_solver_files: bool,
) -> tuple[str, str, np.ndarray | None, np.ndarray | None]:
    captured: dict[str, np.ndarray] = {}
    q_path = _transient_q_artifact(mk, sy)
    map_path = _transient_network_artifact(mk, sy)
    if reuse and q_path.is_file() and (NETWORK_MAP_SOURCE == "steady" or map_path.is_file()):
        q_total = _read_q_csv(q_path)
        network_map = None
        if NETWORK_MAP_SOURCE != "steady":
            with np.load(map_path) as data:
                network_map = np.asarray(data["outflow_drain"], dtype=float).reshape(-1)
        return "completed", "", q_total, network_map

    def metric_fn(ctx, *, objective: str, variable: str):
        del objective, variable
        stack = _extract_outflow_drain_stack(ctx, keep_solver_files=keep_solver_files)
        q_total = q_total_release_from_drain_by_cell(stack)
        captured["q_total_release"] = q_total
        if NETWORK_MAP_SOURCE != "steady":
            captured["network_map"] = _network_map_from_transient_stack(stack)
        return 0.0, {"n_q": float(q_total.size), "q_mean_m3_s": float(np.mean(q_total))}

    start = time.perf_counter()
    result = run_trial_light(
        transient_ctx,
        {**_k_trial_params(mk), "Sy": float(sy)},
        objective="b0_transient",
        variable="outflow_drain",
        metric_fn=metric_fn,
    )
    elapsed = time.perf_counter() - start
    timings.append(
        {
            "kind": "transient",
            "tag": _tag(mk, sy),
            "status": result.status,
            "seconds": elapsed,
            "error": result.error or "",
        }
    )
    print(f"[transient] {_tag(mk, sy)} {result.status} in {elapsed:.1f} s")
    if result.status != "completed":
        return result.status, result.error or "", None, None

    q_total = captured["q_total_release"]
    _write_q_csv(q_path, q_total)
    network_map = captured.get("network_map")
    if network_map is not None:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(map_path, outflow_drain=network_map)
    return "completed", "", q_total, network_map


def _network_map_from_transient_stack(stack: np.ndarray) -> np.ndarray:
    values = np.asarray(stack, dtype=float)
    if NETWORK_MAP_SOURCE == "transient_mean":
        return np.mean(values, axis=0)
    return values[-1].reshape(-1)


def _extract_outflow_drain_stack(ctx, *, keep_solver_files: bool) -> np.ndarray:
    models = list(ctx.execution.models_by_run_id.values())
    if not models:
        raise RuntimeError("No flow model found after lightweight trial.")
    model = models[-1]
    model.post_processing(
        ModflowPostprocessOptions(
            watertable_elevation=False,
            watertable_depth=False,
            seepage_areas=False,
            outflow_drain=True,
            outlet_discharge_east_side_m3_s=False,
            groundwater_flux=False,
            groundwater_storage=False,
            accumulation_flux=False,
            persistency_index=False,
            intermittency_yearly=False,
            intermittency_monthly=False,
            intermittency_weekly=False,
            intermittency_daily=False,
            export_all_tif=False,
            native_mesh_npz=False,
            native_mesh_csv=False,
            native_mesh_vtu=False,
            native_mesh_png=False,
        )
    )
    by_time = getattr(model, "dict_outflow_drain", {})
    if not by_time:
        raise RuntimeError("MODFLOW post-processing produced no outflow_drain.")
    active_mask = _active_cell_mask_from_model(model)
    rows = [
        _expand_active_export_array(
            np.asarray(values, dtype=float).reshape(-1),
            active_mask=active_mask,
        )
        for _, values in sorted(by_time.items(), key=lambda item: int(item[0]))
    ]
    stack = np.vstack(rows)
    if not keep_solver_files:
        scratch = Path(getattr(model, "full_path", ""))
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
    return stack


def _active_cell_mask_from_model(model) -> np.ndarray | None:
    for attr in ("dem_mask", "inactive_mask"):
        raw = getattr(model, attr, None)
        if raw is not None:
            mask = np.asarray(raw, dtype=bool).reshape(-1)
            if mask.size:
                return ~mask
    solver_mesh = getattr(model, "solver_mesh", None)
    raw = getattr(solver_mesh, "inactive_mask", None)
    if raw is not None:
        mask = np.asarray(raw, dtype=bool).reshape(-1)
        if mask.size:
            return ~mask
    return None


def _expand_active_export_array(
    values: np.ndarray, *, active_mask: np.ndarray | None
) -> np.ndarray:
    flat = np.asarray(values, dtype=float).reshape(-1)
    if active_mask is None:
        return flat
    active = np.asarray(active_mask, dtype=bool).reshape(-1)
    if flat.size == active.size:
        out = flat.copy()
        out[~active] = 0.0
        return out
    if flat.size == int(active.sum()):
        out = np.zeros(active.size, dtype=float)
        out[active] = flat
        return out
    return flat


def _score_arrays(steady_drain: np.ndarray, q_total: np.ndarray) -> dict[str, Any]:
    score = score_network_transient_candidate(
        TRUTH_DIR,
        candidate_steady_drain_by_cell=steady_drain,
        candidate_q_total_release=q_total,
    )
    out: dict[str, Any] = {"status": "completed", "objective": float(score.total), "error": ""}
    out.update({key: float(value) for key, value in score.components.items()})
    return out


def _write_score_tables(rows: list[dict[str, Any]], *, also_main: bool) -> None:
    frame = pd.DataFrame(rows)
    if "objective" in frame.columns:
        frame["_status_rank"] = (frame.get("status") == "completed").astype(int)
        frame = (
            frame.sort_values(
                by=["_status_rank", "objective"],
                ascending=[False, True],
                na_position="last",
            )
            .drop(columns=["_status_rank"])
            .reset_index(drop=True)
        )
        frame.insert(0, "rank", range(1, len(frame) + 1))
    LIGHT_SCORES_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(LIGHT_SCORES_CSV, index=False)
    LIGHT_SCORES_JSON.write_text(
        json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if also_main:
        frame.to_csv(GRID_SCORES_CSV, index=False)
        GRID_SCORES_JSON.write_text(
            json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _write_q_csv(path: Path, q_total: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestep", "q_total_release"])
        for idx, value in enumerate(np.asarray(q_total, dtype=float).reshape(-1)):
            writer.writerow([idx, f"{float(value):.16g}"])


def _read_q_csv(path: Path) -> np.ndarray:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return np.asarray([float(row["q_total_release"]) for row in reader], dtype=float)


def _write_k_csv(mk: float) -> Path:
    out = CONFIG_ROOT / f"geology_K_dummy_demo_{_mk_tag(mk)}.csv"
    if out.is_file():
        return out
    with SOURCE_K_CSV.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None or "K_value" not in reader.fieldnames:
            raise ValueError(f"Missing K_value column in {SOURCE_K_CSV}")
        rows = []
        for row in reader:
            row = dict(row)
            row["K_value"] = f"{float(row['K_value']) * mk:.16g}"
            rows.append(row)
    with out.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out


def _k_override_paths() -> dict[str, str]:
    if K_MODE == "homogeneous":
        return {"K_value": "flow.param.K.field.value"}
    return {"K_csv": "flow.param.K.field.values_csv_file"}


def _k_trial_params(mk: float) -> dict[str, Any]:
    if K_MODE == "homogeneous":
        return {"K_value": _k_value_text(mk)}
    return {"K_csv": str(_write_k_csv(mk).resolve())}


def _k_value_text(mk: float) -> str:
    return f"{BASE_K_VALUE * float(mk):.16g} {BASE_K_UNIT}".strip()


def _steady_artifact(mk: float) -> Path:
    return LIGHT_STEADY_DIR / f"{_mk_tag(mk)}_steady_drain.npz"


def _transient_q_artifact(mk: float, sy: float) -> Path:
    return LIGHT_TRANSIENT_DIR / f"{_tag(mk, sy)}_q_total_release.csv"


def _transient_network_artifact(mk: float, sy: float) -> Path:
    return LIGHT_TRANSIENT_DIR / f"{_tag(mk, sy)}_{NETWORK_MAP_SOURCE}_outflow_drain.npz"


def _candidate_id(mk: float, sy: float) -> str:
    if abs(mk - TARGET_MK) < 1.0e-12 and abs(sy - TARGET_SY) < 1.0e-12:
        return f"truth_{_tag(mk, sy)}"
    return _tag(mk, sy)


def _default_dense_mk_values() -> list[float]:
    values = np.concatenate((np.linspace(0.1, 5.0, 24), np.asarray([TARGET_MK])))
    return [float(value) for value in sorted(set(np.round(values, 10)))]


def _default_dense_sy_values() -> list[float]:
    values = np.linspace(0.01, 0.2, 20)
    return [float(value) for value in np.round(values, 10)]


def _steady_root(mk: float) -> Path:
    return REAL_ROOT / f"candidate_{_mk_tag(mk)}_Sy_0p05_steady_mf6"


def _transient_root(mk: float, sy: float) -> Path:
    return REAL_ROOT / f"candidate_{_tag(mk, sy)}_transient_mf6"


def _tag(mk: float, sy: float) -> str:
    return f"{_mk_tag(mk)}_{_sy_tag(sy)}"


def _mk_tag(mk: float) -> str:
    return f"mK_{mk:.2f}".replace(".", "p")


def _sy_tag(sy: float) -> str:
    return f"Sy_{sy:.2f}".replace(".", "p")


def _value_tag(value: float) -> str:
    return f"{float(value):.2f}".replace(".", "p")


def _relative_or_abs(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
