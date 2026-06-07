"""Helpers for publication-safe gallery artifacts."""

from __future__ import annotations

from typing import Any

LEGACY_PATH_REPLACEMENTS = (("_".join(("launcher", "simulation")), "simulation_regression"),)

PUBLIC_COMPARISON_MANIFEST_DROP_KEYS = frozenset(
    {
        "base_simulation_config",
        "comparison_differences_csv",
        "comparison_figures_dir",
        "comparison_audit_json",
        "comparison_audit_md",
        "comparison_metrics_csv",
        "comparison_metrics_json",
        "comparison_report_md",
        "comparison_root",
        "comparison_web_report",
        "config_path",
        "generated_config_cleanup_errors",
        "generated_config_paths",
        "manifest_path",
        "mesh_output_exchange_bundle_dir",
        "mesh_output_mesh",
        "mesh_output_summary_json",
        "observables_csv",
        "period_diagnostics",
        "path",
        "run_folder",
        "runtime_summary",
        "source_path",
        "stderr_tail",
        "stdout_tail",
        "step_diagnostics",
    }
)


def normalize_public_path_text(text: str) -> str:
    """Normalize path-like text before publishing gallery artifacts."""
    normalized = text
    for old, new in LEGACY_PATH_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized


def normalize_public_payload(value: Any) -> Any:
    """Normalize legacy path vocabulary in a JSON-like payload."""
    if isinstance(value, str):
        return normalize_public_path_text(value)
    if isinstance(value, list):
        return [normalize_public_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            normalize_public_payload(key): normalize_public_payload(item)
            for key, item in value.items()
        }
    return value


def _sanitize_public_manifest_payload(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_public_path_text(value)
    if isinstance(value, list):
        return [_sanitize_public_manifest_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = normalize_public_payload(key)
            if normalized_key in PUBLIC_COMPARISON_MANIFEST_DROP_KEYS:
                continue
            sanitized[normalized_key] = _sanitize_public_manifest_payload(item)
        return sanitized
    return value


def sanitize_public_comparison_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove workspace-local paths from a public simulation-comparison manifest."""
    sanitized = _sanitize_public_manifest_payload(payload)
    return sanitized if isinstance(sanitized, dict) else {}
