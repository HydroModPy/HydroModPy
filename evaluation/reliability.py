"""Approximate a SonarQube-style "Reliability" signal using Ruff.

This does not reimplement SonarQube's bug-detection engine -- that
represents years of rule refinement across many languages, and duplicating
it from scratch would just produce a worse version of an already-mature
tool. Instead this reuses Ruff's pyflakes (``F``) and flake8-bugbear
(``B``) rule families, which cover a meaningful, complementary subset of
the same idea: likely-bug patterns (undefined names, mutable default
arguments, loop-variable closures, redefinitions...) rather than style.

Ruff is already a dependency of this project (see ``pyproject.toml``'s
``[tool.ruff.lint]``), and this script runs it with no ``--select``/
``--ignore`` override so it keeps respecting the project's own configured
exceptions (e.g. the deliberate ``B008`` tolerance for Pydantic
``Field(...)`` defaults) -- only the resulting violations are filtered down
to the F/B subset afterwards, in Python.

The A-E "rating" this script computes is our own simple heuristic (worst
severity found, roughly in the spirit of SonarQube's rating), not a
reproduction of SonarQube's proprietary formula.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation._utils import resolve_repository_root

# Codes judged likely to cause an actual runtime failure or a silently wrong
# result, as opposed to a milder style/smell issue (e.g. F401 unused import).
HIGH_SEVERITY_CODES = {
    "F821",  # undefined name -- raises NameError at runtime
    "F823",  # local variable referenced before assignment
    "F811",  # redefinition of unused name -- can silently shadow real logic
    "F706",  # 'return' outside a function
    "F707",  # default 'except' not last
    "B023",  # function/lambda uses a loop variable -- classic late-binding bug
    "B006",  # mutable default argument
}


def _severity(code: str) -> str:
    if code in HIGH_SEVERITY_CODES:
        return "high"
    if code[:1] in {"F", "B"}:
        return "medium"
    return "low"


def run_ruff(root: Path) -> list[dict[str, Any]]:
    ruff_bin = shutil.which("ruff") or shutil.which("ruff.exe")
    command = [ruff_bin] if ruff_bin else [sys.executable, "-m", "ruff"]
    completed = subprocess.run(
        [*command, "check", str(root), "--output-format", "json"],
        capture_output=True,
        text=True,
    )
    # ruff exits 1 when it found violations -- that's expected, not a failure.
    if completed.returncode not in (0, 1):
        raise SystemExit(f"ruff failed: {completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"could not parse ruff output: {completed.stdout[:500]}") from exc


def rating_from_counts(n_high: int, n_medium: int) -> str:
    if n_high >= 5:
        return "E"
    if n_high > 0:
        return "D"
    if n_medium > 20:
        return "C"
    if n_medium > 0:
        return "B"
    return "A"


def compute_reliability(root: Path) -> dict[str, Any]:
    diagnostics = run_ruff(root)
    violations = [item for item in diagnostics if str(item.get("code") or "")[:1] in {"F", "B"}]

    rows: list[dict[str, Any]] = []
    by_code: Counter[str] = Counter()
    by_file: dict[str, dict[str, int]] = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0})

    for item in violations:
        code = str(item.get("code") or "")
        severity = _severity(code)
        filename = item.get("filename", "")
        try:
            relative = str(Path(filename).resolve().relative_to(root.resolve()))
        except ValueError:
            relative = filename

        by_code[code] += 1
        by_file[relative][severity] += 1
        rows.append(
            {
                "file": relative,
                "code": code,
                "severity": severity,
                "message": item.get("message", ""),
                "line": (item.get("location") or {}).get("row"),
            }
        )

    n_high = sum(1 for row in rows if row["severity"] == "high")
    n_medium = sum(1 for row in rows if row["severity"] == "medium")
    n_low = sum(1 for row in rows if row["severity"] == "low")

    worst_files = sorted(
        (
            {"file": file, **counts, "total": sum(counts.values())}
            for file, counts in by_file.items()
        ),
        key=lambda entry: (-entry["high"], -entry["medium"], -entry["total"]),
    )

    return {
        "root": str(root),
        "rating": rating_from_counts(n_high, n_medium),
        "total_violations": len(rows),
        "high_severity": n_high,
        "medium_severity": n_medium,
        "low_severity": n_low,
        "by_code": dict(by_code.most_common(20)),
        "worst_files": worst_files[:20],
        "violations": rows,
    }


def write_reliability_chart(result: dict[str, Any], output_path: Path, top_n: int = 20) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    worst = result.get("worst_files", [])[:top_n]
    if not worst:
        return

    labels = [item["file"] for item in worst]
    high = [item["high"] for item in worst]
    medium = [item["medium"] for item in worst]
    low = [item["low"] for item in worst]
    baseline = [h + m for h, m in zip(high, medium, strict=True)]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(labels))))
    positions = range(len(labels))
    ax.barh(list(positions), high, color="#d62728", label="high")
    ax.barh(list(positions), medium, left=high, color="#ff7f0e", label="medium")
    ax.barh(list(positions), low, left=baseline, color="#7f7f7f", label="low")
    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Violations (pyflakes F + flake8-bugbear B)")
    ax.set_title(f"Reliability -- worst {len(worst)} files (rating: {result['rating']})")
    ax.legend(fontsize=8)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approximate a reliability signal from Ruff's pyflakes/bugbear rules"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    parser.add_argument("--chart", type=Path, default=None, help="Optional bar chart of the worst files")
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = compute_reliability(root)

        output = json.dumps(result, indent=2)

        if args.output is None:
            print(output)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")

        if args.chart is not None:
            write_reliability_chart(result, args.chart)


if __name__ == "__main__":
    main()
