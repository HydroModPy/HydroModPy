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

except ImportError as exc:
    nx = None
    NETWORKX_ERROR = exc

else:
    NETWORKX_ERROR = None


def get_import_name(node: ast.AST) -> str | None:
    """
    Extract full module name from import nodes.
    """

    if isinstance(node, ast.Import):
        if node.names:
            return node.names[0].name

    elif isinstance(node, ast.ImportFrom):
        if node.module:
            return node.module

    return None


def collect_architecture(root: Path) -> dict[str, Any]:

    files = iter_python_files(root)

    module_map = {path: module_name_from_path(root, path) for path in files}

    internal_modules = set(module_map.values())

    graph_data: dict[str, Any] = {
        "root": str(root),
        "modules": [],
        "classes": 0,
        "functions": 0,
        "module_count": len(files),
        "dependencies": [],
    }

    graph = nx.DiGraph() if nx else None

    dependency_edges: set[tuple[str, str]] = set()

    for path in files:
        module = module_map[path]

        tree = parse_ast(path)

        class_count = 0

        function_count = 0

        internal_dependencies: set[str] = set()

        external_dependencies: set[str] = set()

        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_count += 1

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_count += 1

                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imported = get_import_name(node)

                    if imported is None:
                        continue

                    # recherche d'un module interne

                    matching_internal = None

                    for internal in internal_modules:
                        if imported == internal or imported.startswith(internal + "."):
                            matching_internal = internal
                            break

                    if matching_internal:
                        internal_dependencies.add(matching_internal)

                        dependency_edges.add((module, matching_internal))

                    else:
                        external_dependencies.add(imported.split(".")[0])

        module_info = {
            "module": module,
            "path": str(path),
            "lines": count_lines(path),
            "classes": class_count,
            "functions": function_count,
            "internal_dependencies": sorted(internal_dependencies),
            "external_dependencies": sorted(external_dependencies),
        }

        graph_data["modules"].append(module_info)

        graph_data["classes"] += class_count

        graph_data["functions"] += function_count

        if graph is not None:
            graph.add_node(
                module, classes=class_count, functions=function_count, lines=count_lines(path)
            )

            for dependency in internal_dependencies:
                graph.add_edge(module, dependency)

    graph_data["dependencies"] = [
        {"source": source, "target": target} for source, target in sorted(dependency_edges)
    ]

    return {"data": graph_data, "graph": graph}


def _module_to_package(module: str) -> str:
    return module.rsplit(".", 1)[0] if "." in module else module


def _truncate_depth(package: str, depth: int | None) -> str:
    if depth is None:
        return package
    truncated = ".".join(package.split(".")[:depth])
    return truncated or package


def aggregate_graph_to_packages(
    graph: Any,
    depth: int | None = 1,
    top_n: int = 30,
    node_is_module: bool = True,
) -> Any:
    """
    Collapse a module-level dependency graph into a package-level one.

    Drawing every module (hundreds to thousands of nodes for a real
    repository) produces an unreadable image, so image exports go through
    this aggregation by default; GraphML/JSON exports keep full module
    detail since they're meant for external tools, not direct viewing.

    `node_is_module` controls whether nodes are raw module names (so the
    immediate containing package is derived first) or already package
    names (e.g. a graph built by a caller that already aggregated by
    package) — in the latter case only the depth truncation applies.
    """

    if nx is None or graph is None:
        return graph

    def to_package(node: str) -> str:
        package = _module_to_package(node) if node_is_module else node
        return _truncate_depth(package, depth)

    node_counts: dict[str, int] = {}
    for node in graph.nodes():
        package = to_package(node)
        node_counts[package] = node_counts.get(package, 0) + 1

    top_packages = set(
        sorted(node_counts, key=lambda package: node_counts[package], reverse=True)[:top_n]
    )

    package_graph = nx.DiGraph()
    package_graph.add_nodes_from(top_packages)
    for source, target in graph.edges():
        source_package = to_package(source)
        target_package = to_package(target)
        if source_package == target_package:
            continue
        if source_package not in top_packages or target_package not in top_packages:
            continue
        if package_graph.has_edge(source_package, target_package):
            package_graph[source_package][target_package]["weight"] += 1
        else:
            package_graph.add_edge(source_package, target_package, weight=1)

    return package_graph


def save_graph(
    graph: Any,
    output_path: Path,
    package_depth: int | None = 1,
    top_n: int = 30,
    node_is_module: bool = True,
) -> None:

    if graph is None:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix.lower() == ".graphml":
        nx.write_graphml(graph, output_path)

        return

    if output_path.suffix.lower() == ".json":
        data = {
            "nodes": list(graph.nodes(data=True)),
            "edges": list(graph.edges()),
        }

        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return

    try:
        import matplotlib.pyplot as plt

    except ImportError as exc:
        raise RuntimeError("matplotlib is required for image graph output") from exc

    graph = aggregate_graph_to_packages(graph, package_depth, top_n, node_is_module)

    plt.figure(figsize=(16, 10))

    positions = nx.spring_layout(graph, seed=42)

    nx.draw_networkx(graph, positions, node_size=500, font_size=7, arrows=True)

    plt.axis("off")

    plt.tight_layout()

    plt.savefig(output_path, dpi=200)

    plt.close()


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Extract architecture metrics from a Python repository"
    )

    parser.add_argument("--root", type=Path, default=Path.cwd())

    parser.add_argument("--repo", type=str, default=None)

    parser.add_argument("--branch", type=str, default=None)

    parser.add_argument("--output", type=Path, default=None)

    parser.add_argument("--graph-output", type=Path, default=None)

    parser.add_argument(
        "--package-depth",
        type=int,
        default=1,
        help="Number of dotted segments used to group packages in image graph output (1 = top-level package)",
    )

    parser.add_argument(
        "--top-n-packages",
        type=int,
        default=30,
        help="Maximum number of packages shown in image graph output",
    )

    args = parser.parse_args()

    if nx is None:
        raise SystemExit(f"networkx is required: {NETWORKX_ERROR}")

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = collect_architecture(root)

        data = result["data"]

        graph = result["graph"]

        output = json.dumps(data, indent=2)

        if args.output is None:
            print(output)

        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)

            args.output.write_text(output, encoding="utf-8")

        if args.graph_output:
            save_graph(graph, args.graph_output, args.package_depth, args.top_n_packages)


if __name__ == "__main__":
    main()
