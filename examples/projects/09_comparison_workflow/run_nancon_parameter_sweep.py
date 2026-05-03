"""Run a small Nancon MF6/Boussinesq parameter sweep.

The sweep is intentionally external to the simulation code: it materializes one
base simulation TOML and one comparison TOML per parameter scenario, runs the
standard comparison launcher, then summarizes post-run audit diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomli_w

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

PROJECT_DIR = Path(__file__).resolve().parent
EXAMPLES_ROOT = PROJECT_DIR.parents[1]
BASE_CONFIG = PROJECT_DIR / "base_nancon_transient_seasonal.toml"
COMPARISON_TEMPLATE = PROJECT_DIR / "compare_nancon_transient_seasonal_mf6_bouss.toml"
SWEEP_ROOT = PROJECT_DIR / "outputs" / "nancon_parameter_sweep"
CONFIG_ROOT = SWEEP_ROOT / "_configs"
SUMMARY_CSV = SWEEP_ROOT / "nancon_parameter_sweep_summary.csv"

PARAMETER_CASES: dict[str, dict[str, Any]] = {
    "a1_ss3e-4_drn3e-5": {
        "label": "A1 storage correction douce",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "3e-4 m-1",
        "drainage": "3e-5 m2/s",
    },
    "a2_ss1e-3_drn3e-5": {
        "label": "A2 stockage pressurise augmente",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-3 m-1",
        "drainage": "3e-5 m2/s",
    },
    "a3_ss1e-3_drn1e-4": {
        "label": "A3 drainage plus fort",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-3 m-1",
        "drainage": "1e-4 m2/s",
    },
    "b2_k7p5e-5_sy0p07": {
        "label": "B2 compromis K/Sy",
        "K": "7.5e-5 m/s",
        "Sy": "0.07 -",
        "Ss": "1e-3 m-1",
        "drainage": "3e-5 m2/s",
    },
    "b3_k1e-4_sy0p06": {
        "label": "B3 transfert lateral renforce",
        "K": "1e-4 m/s",
        "Sy": "0.06 -",
        "Ss": "1e-3 m-1",
        "drainage": "3e-5 m2/s",
    },
    "c1_ss1e-4_drn1e-4": {
        "label": "C1 battement conserve drainage fort",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-4 m2/s",
    },
    "c2_ss3e-4_drn1e-4": {
        "label": "C2 stockage intermediaire drainage fort",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "3e-4 m-1",
        "drainage": "1e-4 m2/s",
    },
    "c3_ss1e-4_drn3e-4": {
        "label": "C3 battement conserve drainage tres fort",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-4 m2/s",
    },
    "d1_ss1e-4_drn3e-4": {
        "label": "D1 drainance forte isolee",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-4 m2/s",
    },
    "d2_ss1e-4_drn1e-3": {
        "label": "D2 drainance tres forte",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-3 m2/s",
    },
    "d3_ss1e-4_drn3e-3": {
        "label": "D3 drainance extreme",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-3 m2/s",
    },
    "d4_ss1e-4_drn1e-2": {
        "label": "D4 drainance quasi contrainte",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-2 m2/s",
    },
    "e1_ss1e-4_drn3e-4_no_ss": {
        "label": "E1 drainance forte sans premiere periode permanente",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-4 m2/s",
        "mf6_firstpersteady": False,
    },
    "e2_ss1e-4_drn1e-3_no_ss": {
        "label": "E2 drainance tres forte sans premiere periode permanente",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "e3_ss1e-4_drn3e-3_no_ss": {
        "label": "E3 drainance extreme sans premiere periode permanente",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "e4_ss1e-4_drn1e-2_no_ss": {
        "label": "E4 drainance quasi contrainte sans premiere periode permanente",
        "K": "5e-5 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-2 m2/s",
        "mf6_firstpersteady": False,
    },
    "f1_k1e-4_drn1e-3_no_ss": {
        "label": "F1 K augmente drainance tres forte",
        "K": "1e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "f2_k2e-4_drn1e-3_no_ss": {
        "label": "F2 K fortement augmente drainance tres forte",
        "K": "2e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "f3_k3e-4_drn1e-3_no_ss": {
        "label": "F3 K tres eleve drainance tres forte",
        "K": "3e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "1e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "f4_k1e-4_drn3e-3_no_ss": {
        "label": "F4 K augmente drainance extreme",
        "K": "1e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "f5_k2e-4_drn3e-3_no_ss": {
        "label": "F5 K fortement augmente drainance extreme",
        "K": "2e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-3 m2/s",
        "mf6_firstpersteady": False,
    },
    "f6_k3e-4_drn3e-3_no_ss": {
        "label": "F6 K tres eleve drainance extreme",
        "K": "3e-4 m/s",
        "Sy": "0.05 -",
        "Ss": "1e-4 m-1",
        "drainage": "3e-3 m2/s",
        "mf6_firstpersteady": False,
    },
}


def _set_param(payload: dict[str, Any], name: str, value: str) -> None:
    payload["flow"]["param"][name]["field_homogeneous"]["value"] = value


def _materialize_base_config(case_id: str, spec: dict[str, Any]) -> Path:
    payload = load_toml_with_base_config(BASE_CONFIG)
    payload = deepcopy(payload)
    case_root = SWEEP_ROOT / case_id
    payload["workspace"]["project_root"] = str((case_root / "workspace").resolve())
    payload["workspace"]["root"] = str(EXAMPLES_ROOT.resolve())
    payload["simulation"]["name"] = f"nancon_transient_seasonal_{case_id}"
    payload["simulation"]["description"] = "Nancon seasonal benchmark parameter sweep case: " + str(
        spec["label"]
    )
    payload["geographic"]["dem_init_path"] = str(
        (EXAMPLES_ROOT / "data" / "dem" / "DEM_armorican_massif.tif").resolve()
    )
    payload["data"]["dem"]["sources"][0]["path"] = payload["geographic"]["dem_init_path"]

    _set_param(payload, "K", str(spec["K"]))
    _set_param(payload, "Sy", str(spec["Sy"]))
    _set_param(payload, "Ss", str(spec["Ss"]))
    payload["flow"]["bc"]["cauchy"]["drainage"]["value"] = str(spec["drainage"])

    config_dir = CONFIG_ROOT / case_id
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / f"base_nancon_transient_seasonal_{case_id}.toml"
    path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    return path


def _materialize_comparison_config(case_id: str, spec: dict[str, Any], base_path: Path) -> Path:
    payload = load_toml_with_base_config(COMPARISON_TEMPLATE)
    payload = deepcopy(payload)
    case_root = SWEEP_ROOT / case_id
    comparison = payload["comparison"]
    comparison["comparison_id"] = f"nancon_transient_seasonal_{case_id}_mf6_vs_bouss"
    comparison["base_simulation_config"] = str(base_path.resolve())
    comparison["output_root"] = str((case_root / "comparison").resolve())
    comparison["continue_on_error"] = False
    comparison["fine_raster"]["enabled"] = False

    for simulation in comparison["simulation"]:
        sim_id = str(simulation["id"])
        simulation["label"] = f"{simulation['label']} [{spec['label']}]"
        overlay = simulation.setdefault("overlay", {})
        workspace = overlay.setdefault("workspace", {})
        workspace["root"] = str(EXAMPLES_ROOT.resolve())
        workspace["project_root"] = str((case_root / f"workspace_{sim_id}").resolve())
        if sim_id == "mf6_ref" and "mf6_firstpersteady" in spec:
            modflow6 = overlay.setdefault("modflow6", {})
            tgrid = modflow6.setdefault("tgrid", {})
            tgrid["firstpersteady"] = bool(spec["mf6_firstpersteady"])

    config_dir = CONFIG_ROOT / case_id
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / f"compare_nancon_transient_seasonal_{case_id}_mf6_bouss.toml"
    path.write_text(tomli_w.dumps(payload), encoding="utf-8")
    return path


def materialize_case_configs(case_id: str, spec: dict[str, Any]) -> Path:
    base_path = _materialize_base_config(case_id, spec)
    return _materialize_comparison_config(case_id, spec, base_path)


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _max_head_bound(
    audit: dict[str, Any],
    variant_id: str,
    field: str,
    *,
    observable_prefix: str | None = None,
    observable_suffix: str | None = None,
) -> float:
    values: list[float] = []
    for item in audit.get("head_bounds", []):
        if str(item.get("variant_id", "")) != variant_id:
            continue
        observable = str(item.get("observable", ""))
        if observable_prefix is not None and not observable.startswith(observable_prefix):
            continue
        if observable_suffix is not None and not observable.endswith(observable_suffix):
            continue
        value = item.get(field)
        if value in (None, ""):
            continue
        try:
            values.append(float(value))
        except Exception:
            continue
    return max(values) if values else float("nan")


def _head_response(
    audit: dict[str, Any],
    variant_id: str,
    observable: str,
    field: str,
) -> float:
    for item in audit.get("head_recharge_response", []):
        if (
            str(item.get("variant_id", "")) == variant_id
            and str(item.get("observable", "")) == observable
        ):
            value = item.get(field)
            if value in (None, ""):
                return float("nan")
            try:
                return float(value)
            except Exception:
                return float("nan")
    return float("nan")


def summarize_case(
    case_id: str, spec: dict[str, Any], manifest: dict[str, Any] | None
) -> dict[str, Any]:
    comparison_root = SWEEP_ROOT / case_id / "comparison"
    if manifest is not None and manifest.get("comparison_root"):
        comparison_root = Path(str(manifest["comparison_root"]))
    audit = _safe_load_json(comparison_root / "comparison_audit.json")
    recharge_check = {}
    for subject in audit.get("subjects", []):
        if str(subject.get("id", "")) == "bouss_candidate":
            recharge_check = subject.get("budget_checks", {}).get("recharge_total_m3_s", {}) or {}
            break

    return {
        "case_id": case_id,
        "label": spec["label"],
        "K": spec["K"],
        "Sy": spec["Sy"],
        "Ss": spec["Ss"],
        "drainage": spec["drainage"],
        "status": "missing_audit" if not audit else str(audit.get("status", "")),
        "issue_count": len(audit.get("issues", [])) if audit else "",
        "recharge_status": recharge_check.get("status", ""),
        "recharge_max_abs_rel_diff": recharge_check.get("max_abs_rel_diff", ""),
        "mf6_above_top_fraction_max": _max_head_bound(
            audit,
            "mf6_ref",
            "above_top_fraction",
        ),
        "mf6_above_top_max_m": _max_head_bound(audit, "mf6_ref", "above_top_max_m"),
        "mf6_map_above_top_fraction_max": _max_head_bound(
            audit,
            "mf6_ref",
            "above_top_fraction",
            observable_prefix="head_map",
        ),
        "mf6_map_above_top_max_m": _max_head_bound(
            audit,
            "mf6_ref",
            "above_top_max_m",
            observable_prefix="head_map",
        ),
        "mf6_point_above_top_fraction_max": _max_head_bound(
            audit,
            "mf6_ref",
            "above_top_fraction",
            observable_suffix="_series",
        ),
        "mf6_point_above_top_max_m": _max_head_bound(
            audit,
            "mf6_ref",
            "above_top_max_m",
            observable_suffix="_series",
        ),
        "bouss_above_top_fraction_max": _max_head_bound(
            audit,
            "bouss_candidate",
            "above_top_fraction",
        ),
        "bouss_above_top_max_m": _max_head_bound(
            audit,
            "bouss_candidate",
            "above_top_max_m",
        ),
        "mf6_outlet_head_range_m": _head_response(
            audit,
            "mf6_ref",
            "head_outlet_series",
            "head_range_m",
        ),
        "mf6_mid_head_range_m": _head_response(
            audit,
            "mf6_ref",
            "head_mid_catchment_series",
            "head_range_m",
        ),
        "mf6_outlet_corr_delta_recharge_delta_head": _head_response(
            audit,
            "mf6_ref",
            "head_outlet_series",
            "corr_delta_recharge_delta_head",
        ),
        "mf6_mid_corr_delta_recharge_delta_head": _head_response(
            audit,
            "mf6_ref",
            "head_mid_catchment_series",
            "corr_delta_recharge_delta_head",
        ),
        "bouss_outlet_head_range_m": _head_response(
            audit,
            "bouss_candidate",
            "head_outlet_series",
            "head_range_m",
        ),
        "bouss_mid_head_range_m": _head_response(
            audit,
            "bouss_candidate",
            "head_mid_catchment_series",
            "head_range_m",
        ),
        "comparison_root": str(comparison_root),
        "report": str(comparison_root / "comparison_report.md"),
        "audit": str(comparison_root / "comparison_audit.md"),
    }


def write_summary(rows: list[dict[str, Any]]) -> None:
    SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _selected_cases(case_ids: list[str] | None) -> dict[str, dict[str, Any]]:
    if not case_ids:
        return PARAMETER_CASES
    unknown = sorted(set(case_ids).difference(PARAMETER_CASES))
    if unknown:
        raise ValueError(f"Unknown case id(s): {', '.join(unknown)}")
    return {case_id: PARAMETER_CASES[case_id] for case_id in case_ids}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(PARAMETER_CASES),
        help="Case id to run. Can be repeated. Defaults to all cases.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only materialize TOML configs and write no run outputs.",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Do not run simulations; reuse existing stores and regenerate comparisons.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue the sweep if one scenario fails.",
    )
    args = parser.parse_args(argv)

    rows: list[dict[str, Any]] = []
    for case_id, spec in _selected_cases(args.case).items():
        print(f"=== {case_id}: {spec['label']} ===", flush=True)
        compare_path = materialize_case_configs(case_id, spec)
        manifest: dict[str, Any] | None = None
        if not args.prepare_only:
            try:
                launcher = SimulationComparisonLauncher(compare_path)
                if args.reuse:
                    launcher.cfg.comparison.execution.run_simulations = False
                manifest = launcher.run()
                print(f"  audit: {manifest.get('audit_status', '')}", flush=True)
                print(f"  output: {manifest.get('comparison_root', '')}", flush=True)
            except Exception:
                traceback.print_exc()
                if not args.continue_on_error:
                    raise
        rows.append(summarize_case(case_id, spec, manifest))

    write_summary(rows)
    print(f"Summary: {SUMMARY_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
