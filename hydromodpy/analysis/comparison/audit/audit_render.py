"""Markdown and JSON renderers for the simulation-comparison audit."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .audit_io import RECHARGE_COMPONENT


def write_audit_files(
    *,
    comparison_root: Path,
    audit: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Write machine-readable and Markdown audit summaries."""
    comparison_root.mkdir(parents=True, exist_ok=True)
    json_path = comparison_root / "comparison_audit.json"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    lines = [
        f"# Comparison Audit: {audit.get('status', '')}",
        "",
        f"- Reference simulation: `{audit.get('reference_simulation', '')}`",
        f"- Mode: `{audit.get('mode', '')}`",
        f"- Issues: {len(audit.get('issues', []))}",
        f"- Physical config sections: {len(audit.get('physical_config_sections', []))}",
        "",
        "## Issues",
    ]
    issues = list(audit.get("issues", []))
    ignored_issues = list(audit.get("ignored_issues", []))
    if not issues:
        lines.append("- No equivalence issue detected.")
    else:
        for issue in issues:
            field = issue.get("field")
            suffix = f" field=`{field}`" if field else ""
            simulation_id = issue.get("simulation_id", "")
            lines.append(
                f"- `{issue.get('level', '')}` / `{issue.get('kind', '')}`"
                f" simulation=`{simulation_id}`{suffix}"
            )
    if ignored_issues:
        lines.extend(["", "## Ignored Differences"])
        for issue in ignored_issues:
            field = issue.get("field")
            suffix = f" field=`{field}`" if field else ""
            simulation_id = issue.get("simulation_id", "")
            lines.append(
                f"- `{issue.get('kind', '')}` simulation=`{simulation_id}`{suffix}: "
                f"{issue.get('message', '')}"
            )
    config_issue_count = sum(
        1 for issue in issues if issue.get("kind") == "config_section_mismatch"
    )
    lines.extend(["", "## Physical Config Checks"])
    if config_issue_count:
        lines.append(f"- Physical config section mismatches: {config_issue_count}.")
    else:
        lines.append("- No physical config section mismatch detected.")

    lines.extend(["", "## Recharge Budget Checks"])
    subjects = list(audit.get("subjects", []))
    wrote_check = False
    for subject in subjects:
        checks = subject.get("budget_checks", {})
        check = checks.get(RECHARGE_COMPONENT)
        if not isinstance(check, Mapping):
            continue
        wrote_check = True
        lines.append(
            "- "
            f"`{subject.get('id', '')}` / `{RECHARGE_COMPONENT}`: "
            f"status=`{check.get('status', '')}`, "
            f"pairs={check.get('n_pairs', '')}, "
            f"max_abs_diff={check.get('max_abs_diff', '')}, "
            f"max_abs_rel_diff={check.get('max_abs_rel_diff', '')}"
        )
    if not wrote_check:
        lines.append("- No comparable recharge budget check was produced.")

    initial_policy = list(audit.get("initial_state_policy", []))
    lines.extend(["", "## Initial-State Policy"])
    if not initial_policy:
        lines.append("- No mixed initial-state policy was detected.")
    else:
        for item in initial_policy:
            with_initial = ", ".join(item.get("simulations_with_initial_state", []))
            without_initial = ", ".join(item.get("simulations_without_initial_state", []))
            lines.append(
                "- "
                f"`{item.get('observable', '')}` requested_time=`{item.get('requested_time', '')}`: "
                f"with_initial=`{with_initial}`, without_initial=`{without_initial}`, "
                f"severity=`{item.get('severity', '')}`"
            )

    head_bounds = list(audit.get("head_bounds", []))
    lines.extend(["", "## Head Bounds"])
    if not head_bounds:
        lines.append("- No head/top-bottom diagnostic was produced.")
    else:
        for item in head_bounds:
            simulation_id = item.get("simulation_id", "")
            lines.append(
                "- "
                f"`{simulation_id}` / `{item.get('observable', '')}`: "
                f"above_top_fraction={item.get('above_top_fraction', '')}, "
                f"above_top_max_m={item.get('above_top_max_m', '')}, "
                f"below_bottom_fraction={item.get('below_bottom_fraction', '')}"
            )

    diagnostics = list(audit.get("head_recharge_response", []))
    lines.extend(["", "## Head-Recharge Response"])
    if not diagnostics:
        lines.append("- No point-head diagnostic was produced.")
    else:
        for item in diagnostics:
            simulation_id = item.get("simulation_id", "")
            lines.append(
                "- "
                f"`{simulation_id}` / `{item.get('observable', '')}`: "
                f"head_range_m={item.get('head_range_m', '')}, "
                f"corr_delta_recharge_delta_head={item.get('corr_delta_recharge_delta_head', '')}, "
                f"same_sign_delta_fraction={item.get('same_sign_delta_fraction', '')}"
            )
    md_path = comparison_root / "comparison_audit.md"
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path
