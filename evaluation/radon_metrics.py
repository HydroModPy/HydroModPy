from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation._utils import (
    iter_python_files,
    module_name_from_path,
    parse_ast,
    resolve_repository_root,
)

try:
    from radon.complexity import cc_visit
    from radon.metrics import h_visit, mi_visit
except ImportError as exc:  # pragma: no cover - optional dependency
    cc_visit = h_visit = mi_visit = None
    RADON_ERROR = exc
else:
    RADON_ERROR = None


def compute_radon_metrics(root: Path) -> dict[str, Any]:
    files = iter_python_files(root)
    metrics: list[dict[str, Any]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        tree = parse_ast(path)
        complexity = []
        maintainability_index = None
        halstead = None
        if cc_visit is not None:
            complexity = [
                {
                    "name": block.name,
                    "complexity": block.complexity,
                    "lineno": block.lineno,
                    "col_offset": getattr(block, "col_offset", None),
                }
                for block in cc_visit(text)
            ]
            maintainability_index = mi_visit(text, False)
            halstead = h_visit(text)._asdict()
        metrics.append(
            {
                "module": module_name_from_path(root, path),
                "path": str(path),
                "syntax_ok": tree is not None,
                "complexity": complexity,
                "maintainability_index": maintainability_index,
                "halstead": halstead,
            }
        )
    return {"root": str(root), "files": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute radon metrics for a repository")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    args = parser.parse_args()

    if cc_visit is None:
        raise SystemExit(f"radon is required: {RADON_ERROR}")

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = compute_radon_metrics(root)

        if args.output is None:
            print(json.dumps(result, indent=2))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
