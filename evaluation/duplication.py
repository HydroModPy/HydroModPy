"""Detect near-duplicate functions/methods across a repository.

Neither CBO nor LCOM can see this: two adapters (or two report builders)
implementing nearly identical logic score fine on both metrics, yet they are
a real maintenance risk (a fix applied to one copy is silently missed in the
other). This script hashes each function's body after stripping formatting
and renaming local identifiers to placeholders, so two functions that differ
only by variable names or whitespace still match.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import defaultdict
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

MIN_STATEMENTS = 5


class _IdentifierRenamer(ast.NodeTransformer):
    """Replace local names/parameters with positional placeholders.

    Keeps calls, attributes, and literals untouched so the signature still
    reflects actual behavior; only naming choices are erased.
    """

    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}

    def _placeholder(self, name: str) -> str:
        if name in {"self", "cls"} or name.startswith("__"):
            return name
        if name not in self.mapping:
            self.mapping[name] = f"_v{len(self.mapping)}"
        return self.mapping[name]

    def visit_Name(self, node: ast.Name) -> ast.Name:
        self.generic_visit(node)
        return ast.copy_location(ast.Name(id=self._placeholder(node.id), ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        return ast.copy_location(ast.arg(arg=self._placeholder(node.arg), annotation=None), node)


def _normalized_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a formatting- and naming-independent text signature of a function body."""
    renamer = _IdentifierRenamer()
    for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        renamer._placeholder(arg.arg)

    body_module = ast.Module(
        body=[ast.fix_missing_locations(stmt) for stmt in node.body],
        type_ignores=[],
    )
    renamed = renamer.visit(body_module)
    return ast.unparse(renamed)


def compute_duplication(root: Path, min_statements: int = MIN_STATEMENTS) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path in iter_python_files(root):
        tree = parse_ast(path)
        if tree is None:
            continue
        module = module_name_from_path(root, path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if len(node.body) < min_statements:
                continue
            try:
                signature = _normalized_signature(node)
            except Exception:
                continue
            digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
            groups[digest].append(
                {
                    "module": module,
                    "path": str(path),
                    "name": node.name,
                    "lineno": node.lineno,
                    "statements": len(node.body),
                }
            )

    duplicate_groups = [
        {
            "occurrences": len(members),
            "members": sorted(members, key=lambda member: (member["module"], member["lineno"])),
        }
        for members in groups.values()
        if len(members) > 1
    ]
    duplicate_groups.sort(key=lambda group: (-group["occurrences"], -group["members"][0]["statements"]))

    return {
        "root": str(root),
        "min_statements": min_statements,
        "duplicate_groups": duplicate_groups,
    }


def write_duplication_chart(result: dict[str, Any], output_path: Path, top_n: int = 20) -> None:
    """Bar chart of the largest near-duplicate groups, one bar per group.

    Each bar is labeled with the function name and how many places it was
    found in; the first occurrence's module is added for orientation.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    groups = result.get("duplicate_groups", [])[:top_n]
    if not groups:
        return

    labels = []
    counts = []
    for group in groups:
        first = group["members"][0]
        labels.append(f"{first['name']}  ({first['module']}, +{group['occurrences'] - 1})")
        counts.append(group["occurrences"])

    fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(labels))))
    positions = range(len(labels))
    ax.barh(list(positions), counts, color="#d62728")
    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Occurrences")
    ax.set_title(f"Top {len(groups)} near-duplicate functions/methods")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect near-duplicate functions/methods")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout")
    parser.add_argument(
        "--min-statements",
        type=int,
        default=MIN_STATEMENTS,
        help="Ignore functions with fewer top-level statements than this (avoids trivial-function noise)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    parser.add_argument("--chart", type=Path, default=None, help="Optional bar chart of the top duplicate groups")
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = compute_duplication(root, args.min_statements)

        output = json.dumps(result, indent=2)

        if args.output is None:
            print(output)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")

        if args.chart is not None:
            write_duplication_chart(result, args.chart)


if __name__ == "__main__":
    main()
