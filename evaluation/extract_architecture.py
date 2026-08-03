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
    count_lines,
    iter_python_files,
    module_name_from_path,
    parse_ast,
    resolve_repository_root,
)

try:
    import networkx as nx
except ImportError as exc:  # pragma: no cover - optional dependency
    nx = None
    NETWORKX_ERROR = exc
else:
    NETWORKX_ERROR = None


def collect_architecture(root: Path) -> dict[str, Any]:
    files = iter_python_files(root)
    module_map = {path: module_name_from_path(root, path) for path in files}
    internal_modules = set(module_map.values())
    graph_data: dict[str, Any] = {
        "root": str(root),
        "modules": [],
        "classes": 0,
        "functions": 0,
        "dependencies": [],
        "internal_dependencies": [],
    }
    graph = nx.DiGraph() if nx is not None else None

    for path in files:
        module = module_map[path]
        tree = parse_ast(path)
        class_count = 0
        function_count = 0
        dependencies: set[str] = set()
        internal_dependencies: set[str] = set()
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_count += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_count += 1
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        dependencies.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        dependencies.add(node.module.split(".")[0])
                        candidate = node.module
                        while candidate:
                            if candidate in internal_modules:
                                internal_dependencies.add(candidate)
                                break
                            if "." not in candidate:
                                break
                            candidate = candidate.rsplit(".", 1)[0]
        graph_data["modules"].append(
            {
                "module": module,
                "path": str(path),
                "lines": count_lines(path),
                "classes": class_count,
                "functions": function_count,
                "imports": sorted(dependencies),
                "internal_imports": sorted(internal_dependencies),
            }
        )
        graph_data["classes"] += class_count
        graph_data["functions"] += function_count
        if graph is not None:
            graph.add_node(module, path=str(path))
            for dependency in internal_dependencies:
                graph.add_edge(module, dependency)

    graph_data["dependencies"] = [
        {"source": source, "target": target}
        for source, target in sorted(
            {
                (module, dependency)
                for module_info in graph_data["modules"]
                for dependency in module_info["internal_imports"]
                for module in [module_info["module"]]
            }
        )
    ]
    graph_data["module_count"] = len(graph_data["modules"])
    graph_data["graph"] = graph
    return graph_data


def save_graph(graph: Any, output_path: Path) -> None:
    if graph is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".graphml":
        nx.write_graphml(graph, output_path)
        return
    if output_path.suffix.lower() == ".json":
        data = {
            "nodes": list(graph.nodes()),
            "edges": list(graph.edges()),
        }
        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plt.figure(figsize=(16, 10))
    positions = nx.spring_layout(graph, seed=42)
    nx.draw_networkx(graph, positions, node_size=500, font_size=7, arrows=True)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract architecture metrics from a Python repository")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    parser.add_argument("--graph-output", type=Path, default=None, help="Optional graph output path")
    args = parser.parse_args()

    if nx is None:
        raise SystemExit(f"networkx is required: {NETWORKX_ERROR}")

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = collect_architecture(root)
        graph = result.pop("graph")

        if args.output is None:
            print(json.dumps(result, indent=2))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")

        if args.graph_output is not None:
            save_graph(graph, args.graph_output)


if __name__ == "__main__":
    main()
