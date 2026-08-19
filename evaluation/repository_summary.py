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
    is_public_module_path,
    iter_python_files,
    module_name_from_path,
    package_name_from_path,
    parse_ast,
    resolve_repository_root,
)


class SummaryVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.classes = 0
        self.methods = 0
        self.functions = 0
        self.in_class = False

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.classes += 1
        previous = self.in_class
        self.in_class = True
        for item in node.body:
            self.visit(item)
        self.in_class = previous

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        if self.in_class:
            self.methods += 1
        else:
            self.functions += 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.visit_FunctionDef(node)


def summarize_repository(root: Path) -> dict[str, Any]:
    files = iter_python_files(root)
    rows: list[dict[str, Any]] = []
    package_map: dict[str, dict[str, Any]] = {}
    public_modules: list[dict[str, Any]] = []

    total_classes = 0
    total_methods = 0
    total_functions = 0

    for path in files:
        tree = parse_ast(path)
        visitor = SummaryVisitor()
        if tree is not None:
            visitor.visit(tree)

        total_classes += visitor.classes
        total_methods += visitor.methods
        total_functions += visitor.functions

        package = package_name_from_path(root, path)
        public = is_public_module_path(path)
        row = {
            "module": module_name_from_path(root, path),
            "package": package,
            "public": public,
            "path": str(path),
            "lines": count_lines(path),
            "classes": visitor.classes,
            "methods": visitor.methods,
            "functions": visitor.functions,
        }
        rows.append(row)

        if public:
            public_modules.append(row)

        package_row = package_map.setdefault(
            package,
            {
                "package": package,
                "file_count": 0,
                "module_count": 0,
                "public_module_count": 0,
                "class_count": 0,
                "method_count": 0,
                "function_count": 0,
                "line_count": 0,
            },
        )
        package_row["file_count"] += 1
        package_row["module_count"] += 1
        package_row["public_module_count"] += 1 if public else 0
        package_row["class_count"] += visitor.classes
        package_row["method_count"] += visitor.methods
        package_row["function_count"] += visitor.functions
        package_row["line_count"] += row["lines"]

    packages = sorted(
        package_map.values(),
        key=lambda item: (-item["line_count"], item["package"]),
    )
    top_modules = sorted(
        public_modules if public_modules else rows,
        key=lambda item: (-item["lines"], item["module"]),
    )[:25]

    return {
        "root": str(root),
        "file_count": len(files),
        "module_count": len({row["module"] for row in rows}),
        "class_count": total_classes,
        "method_count": total_methods,
        "function_count": total_functions,
        "public_module_count": len(public_modules),
        "files": rows,
        "packages": packages,
        "top_modules": top_modules,
    }


def write_csv(summary: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["module", "package", "public", "path", "lines", "classes", "methods", "functions"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary["files"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a Python repository")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repo", type=str, default=None)
    parser.add_argument("--branch", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
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
