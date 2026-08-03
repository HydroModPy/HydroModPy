from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation._utils import (
    count_lines,
    iter_python_files,
    module_name_from_path,
    parse_ast,
    resolve_repository_root,
)


def summarize_repository(root: Path) -> dict[str, Any]:
    files = iter_python_files(root)
    rows: list[dict[str, Any]] = []
    total_classes = 0
    total_functions = 0
    for path in files:
        tree = parse_ast(path)
        class_count = 0
        function_count = 0
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_count += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_count += 1
        total_classes += class_count
        total_functions += function_count
        rows.append(
            {
                "module": module_name_from_path(root, path),
                "path": str(path),
                "lines": count_lines(path),
                "classes": class_count,
                "functions": function_count,
            }
        )
    return {
        "root": str(root),
        "file_count": len(files),
        "module_count": len({row["module"] for row in rows}),
        "class_count": total_classes,
        "function_count": total_functions,
        "files": rows,
    }


def write_csv(summary: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["module", "path", "lines", "classes", "functions"])
        writer.writeheader()
        writer.writerows(summary["files"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a Python repository")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    parser.add_argument("--csv", type=Path, default=None, help="Optional CSV file")
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = summarize_repository(root)
        if args.output is None:
            print(json.dumps(result, indent=2))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if args.csv is not None:
            write_csv(result, args.csv)


if __name__ == "__main__":
    main()
