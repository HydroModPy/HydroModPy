from __future__ import annotations

import argparse
import ast
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


def compute_cbo(root: Path) -> dict[str, Any]:
    files = iter_python_files(root)
    rows: list[dict[str, Any]] = []
    for path in files:
        tree = parse_ast(path)
        imported_modules: set[str] = set()
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module.split(".")[0])
        rows.append(
            {
                "module": module_name_from_path(root, path),
                "path": str(path),
                "cbo": len(imported_modules),
                "dependencies": sorted(imported_modules),
            }
        )
    return {"root": str(root), "files": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute coupling metrics for a repository")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = compute_cbo(root)
        if args.output is None:
            print(json.dumps(result, indent=2))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
