"""IO helpers for the simulation-comparison equivalence audit.

Hosts shared constants, JSON canonicalization helpers, and subject loaders
that bind audit data to the catalog store and the TOML config snapshot.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.runtime import metadata as runtime_metadata
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

_ORIGINAL_DISCOVER_RESULT_STORE = runtime_metadata.discover_result_store
discover_result_store = _ORIGINAL_DISCOVER_RESULT_STORE


def _discover_result_store(*args: Any, **kwargs: Any) -> Any:
    """Resolve stores while preserving old test monkeypatch entry points."""
    local_func = globals().get("discover_result_store", _ORIGINAL_DISCOVER_RESULT_STORE)
    module_func = runtime_metadata.discover_result_store
    if local_func is not _ORIGINAL_DISCOVER_RESULT_STORE and local_func is not module_func:
        return local_func(*args, **kwargs)
    return module_func(*args, **kwargs)


STRICT_METADATA_KEYS = (
    "mesh_hash",
    "mesh_topology",
    "n_cells",
    "n_layers",
    "n_timesteps",
    "crs_epsg",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
    "period_start",
    "period_end",
    "time_unit",
    "geographic_fingerprint",
)

PHYSICAL_CONFIG_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("simulation.time", ("simulation", "time")),
    ("geographic", ("geographic",)),
    ("domain", ("domain",)),
    ("mesh_catchment", ("mesh_catchment",)),
    ("mesh_input", ("mesh_input",)),
    ("data.recharge", ("data", "recharge")),
    ("flow.flow_regime", ("flow", "flow_regime")),
    ("flow.active_sinks_sources", ("flow", "active_sinks_sources")),
    ("flow.active_bc", ("flow", "active_bc")),
    ("flow.param", ("flow", "param")),
    ("flow.ic", ("flow", "ic")),
    ("flow.bc", ("flow", "bc")),
    ("flow.sinks_sources.recharge", ("flow", "sinks_sources", "recharge")),
)

RECHARGE_COMPONENT = "recharge_total_m3_s"
RECHARGE_REL_TOL = 1.0e-2
RECHARGE_ABS_TOL_M3_S = 1.0e-6
HEAD_ABOVE_TOP_FRACTION_TOL = 5.0e-2
HEAD_ABOVE_TOP_TOL_M = 0.1
INITIAL_STATE_MISMATCH_SELECTORS = {"first", "initial", "initial_state"}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, bool)):
        return value
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    return str(value)


def _normalized_value(value: Any) -> str:
    item = _jsonable(value)
    return "" if item is None else str(item)


def _canonical_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_payload(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return float(f"{value:.15g}")
    return _jsonable(value)


def _nested_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _section_fingerprint(value: Any) -> str:
    return json.dumps(_canonical_payload(value), sort_keys=True, separators=(",", ":"))


def _config_signature(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {"status": "missing_config_path", "sections": {}, "fingerprints": {}}
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception as exc:
        return {
            "status": "load_error",
            "message": str(exc),
            "sections": {},
            "fingerprints": {},
        }

    sections: dict[str, Any] = {}
    fingerprints: dict[str, str] = {}
    for label, path in PHYSICAL_CONFIG_SECTIONS:
        value = _canonical_payload(_nested_value(payload, path))
        if value is None:
            continue
        sections[label] = value
        fingerprints[label] = _section_fingerprint(value)
    return {
        "status": "loaded",
        "config_path": str(config_path),
        "sections": sections,
        "fingerprints": fingerprints,
    }


def _simulation_row(store: Any, sim_id: str) -> dict[str, Any]:
    sims = store.list_simulations()
    if sims.empty or "sim_id" not in sims.columns:
        return {}
    matches = sims.loc[sims["sim_id"].astype(str) == str(sim_id)]
    if matches.empty:
        return {}
    return {key: _jsonable(value) for key, value in matches.iloc[-1].to_dict().items()}


def _parameter_signature(store: Any, sim_id: str) -> list[dict[str, Any]]:
    try:
        rows = store.connection.execute(
            """
            SELECT param_name, zone_id, value, unit, parameterization
              FROM parameters
             WHERE sim_id = ?
             ORDER BY param_name, zone_id
            """,
            [str(sim_id)],
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "param_name": str(row[0]),
            "zone_id": str(row[1]),
            "value": None if row[2] is None else float(row[2]),
            "unit": "" if row[3] is None else str(row[3]),
            "parameterization": "" if row[4] is None else str(row[4]),
        }
        for row in rows
    ]


def _budget_rows(summary: Mapping[str, Any], store: Any, sim_id: str) -> list[dict[str, Any]]:
    try:
        from hydromodpy.analysis.comparison.exports import (
            _load_boussinesq_budget_rows,
            _load_catalog_budget_rows,
        )

        rows = _load_catalog_budget_rows(summary, store, sim_id)
        rows.extend(_load_boussinesq_budget_rows(summary, store=store, sim_id=sim_id))
        return rows
    except Exception:
        return []


def _component_series(
    rows: Iterable[Mapping[str, Any]],
    component: str,
) -> dict[str, float]:
    series: dict[str, float] = {}
    for row in rows:
        if str(row.get("component", "")) != component:
            continue
        try:
            elapsed = float(row.get("elapsed_seconds"))
            value = float(row.get("value"))
        except Exception:
            continue
        if not (math.isfinite(elapsed) and math.isfinite(value)):
            continue
        series[f"elapsed_seconds:{elapsed:.9g}"] = value
    return series


def _load_audit_subject(summary: Mapping[str, Any]) -> dict[str, Any]:
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    preferred_sim_id = summary.get("sim_id")
    preferred_name = summary.get("run_name")
    store, sim_id = _discover_result_store(
        config_path,
        preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
        preferred_name=None if preferred_name in (None, "") else str(preferred_name),
    )
    try:
        config_signature = _config_signature(config_path)
        if store is None or sim_id is None:
            return {
                "id": summary.get("id", ""),
                "solver": summary.get("solver", ""),
                "status": "missing_store",
                "metadata": {},
                "parameters": [],
                "physical_config": config_signature,
                "budget_components": {},
            }
        budget_rows = _budget_rows(summary, store, str(sim_id))
        recharge_series = _component_series(budget_rows, RECHARGE_COMPONENT)
        return {
            "id": summary.get("id", ""),
            "solver": summary.get("solver", ""),
            "status": "loaded",
            "sim_id": str(sim_id),
            "metadata": _simulation_row(store, str(sim_id)),
            "parameters": _parameter_signature(store, str(sim_id)),
            "physical_config": config_signature,
            "budget_components": {
                RECHARGE_COMPONENT: {
                    "summary": _series_summary(recharge_series),
                    "series": recharge_series,
                }
            },
        }
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _series_summary(series: Mapping[str, float]) -> dict[str, Any]:
    values = [float(value) for value in series.values() if math.isfinite(float(value))]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }
