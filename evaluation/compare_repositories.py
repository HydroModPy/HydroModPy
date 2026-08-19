from __future__ import annotations

import argparse
import math
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import matplotlib.pyplot as plt
    import pandas as pd
except ImportError as exc:  # pragma: no cover - optional dependency
    plt = None
    pd = None
    OPTIONAL_ERROR = exc
else:
    OPTIONAL_ERROR = None

from evaluation._utils import resolve_repository_root
from evaluation.cohesion import compute_cohesion
from evaluation.coupling import compute_cbo
from evaluation.extract_architecture import collect_architecture
from evaluation.radon_metrics import compute_radon_metrics
from evaluation.repository_summary import summarize_repository


def load_summary(path: Path) -> dict[str, Any]:
    if path.is_dir():
        return summarize_repository(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".csv":
        if pd is None:
            raise SystemExit(f"pandas is required: {OPTIONAL_ERROR}")
        frame = pd.read_csv(path)
        return {"files": frame.to_dict(orient="records")}
    raise SystemExit(f"Unsupported summary format: {path}")


def _apply_subpath(root: Path, subpath: str | None) -> Path:
    if not subpath:
        return root
    resolved = root / subpath
    if not resolved.is_dir():
        raise SystemExit(f"Subpath {subpath!r} not found under {root}")
    return resolved


def load_or_summarize(
    path: Path | None,
    repo: str | None,
    branch: str | None,
    label: str,
    subpath: str | None = None,
) -> dict[str, Any]:
    if path is not None:
        return load_summary(path)
    if repo is not None:
        with resolve_repository_root(None, repo, branch) as root:
            return summarize_repository(_apply_subpath(root, subpath))
    raise SystemExit(f"Missing input for {label}: provide either a summary file or a repository")


def label_from_path_or_repo(
    path: Path | None,
    repo: str | None,
    default: str,
    override: str | None = None,
) -> str:
    if override:
        return override
    if path is not None:
        return path.stem
    if repo is None:
        return default
    parsed = urlparse(repo)
    if parsed.scheme and parsed.path:
        candidate = Path(parsed.path.rstrip("/")).stem
        return candidate or default
    return Path(repo.rstrip("/")).stem or default


def load_metrics(
    path: Path | None,
    repo: str | None,
    branch: str | None,
    subpath: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if path is not None:
        if path.is_dir():
            with resolve_repository_root(path, None, None) as root:
                root = _apply_subpath(root, subpath)
                architecture = collect_architecture(root)
                return (
                    summarize_repository(root),
                    compute_radon_metrics(root),
                    compute_cbo(root),
                    compute_cohesion(root),
                    architecture.get("data", architecture),
                )
        raise SystemExit("--output-dir requires --left-repo/--right-repo or repository directories, not summary files")
    if repo is not None:
        with resolve_repository_root(None, repo, branch) as root:
            root = _apply_subpath(root, subpath)
            architecture = collect_architecture(root)
            return (
                summarize_repository(root),
                compute_radon_metrics(root),
                compute_cbo(root),
                compute_cohesion(root),
                architecture.get("data", architecture),
            )
    raise SystemExit("Missing repository input")


def flatten_complexities(radon: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for file_info in radon.get("files", []):
        for block in file_info.get("complexity", []):
            complexity = block.get("complexity")
            if isinstance(complexity, (int, float)):
                values.append(float(complexity))
    return values


def flatten_complexities_detailed(radon: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_info in radon.get("files", []):
        module = file_info.get("module")
        path = file_info.get("path")
        for block in file_info.get("complexity", []):
            complexity = block.get("complexity")
            if isinstance(complexity, (int, float)):
                rows.append({"module": module, "path": path, "name": block.get("name"), "complexity": float(complexity)})
    return rows


def top_outliers_text(rows: list[dict[str, Any]], n: int = 5) -> str:
    if not rows:
        return ""
    top = sorted(rows, key=lambda row: row["complexity"], reverse=True)[:n]
    lines = [f"{row.get('module')}::{row.get('name')} = {row['complexity']:.1f}" for row in top]
    return "Valeurs extremes:\n" + "\n".join(lines)


def mean_or_zero(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def file_level_metric(file_infos: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for file_info in file_infos:
        value = file_info.get(field)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def class_level_lcom(cohesion: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for file_info in cohesion.get("files", []):
        for class_info in file_info.get("classes", []):
            lcom = class_info.get("lcom")
            if isinstance(lcom, (int, float)):
                values.append(float(lcom))
    return values


def class_level_cbo(cbo: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for file_info in cbo.get("files", []):
        for class_info in file_info.get("classes", []):
            value = class_info.get("cbo")
            if isinstance(value, (int, float)):
                values.append(float(value))
    return values


def halstead_values(radon: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for file_info in radon.get("files", []):
        halstead = file_info.get("halstead") or {}
        total = halstead.get("total") or {}
        volume = total.get("volume")
        if isinstance(volume, (int, float)):
            values.append(float(volume))
    return values


def repo_summary_metrics(summary: dict[str, Any], radon: dict[str, Any], cbo: dict[str, Any], cohesion: dict[str, Any]) -> dict[str, float]:
    files = summary.get("files", [])
    complexity_values = flatten_complexities(radon)
    maintainability_values = file_level_metric(radon.get("files", []), "maintainability_index")
    cbo_values = class_level_cbo(cbo)
    lcom_values = class_level_lcom(cohesion)
    halstead = halstead_values(radon)
    return {
        "Complexité moyenne": mean_or_zero(complexity_values),
        "Maintainability Index": mean_or_zero(maintainability_values),
        "CBO": mean_or_zero(cbo_values),
        "LCOM": mean_or_zero(lcom_values),
        "Nombre de classes": float(sum(item.get("classes", 0) for item in files)),
        "Nombre de modules": float(len(files)),
        "Nombre de fonctions": float(sum(item.get("functions", 0) for item in files)),
        "Halstead": mean_or_zero(halstead),
    }


def _module_to_package(module: str, depth: int | None = None) -> str:
    package = module.rsplit(".", 1)[0] if "." in module else module
    if depth is not None:
        package = ".".join(package.split(".")[:depth]) or package
    return package


def repo_package_dependency_matrix(
    architecture: dict[str, Any],
    depth: int | None = 1,
    top_n: int = 30,
) -> tuple[list[str], list[list[int]]]:
    node_counts: dict[str, int] = defaultdict(int)
    for module_info in architecture.get("modules", []):
        module = module_info.get("module")
        if module:
            node_counts[_module_to_package(module, depth)] += 1

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for dependency in architecture.get("dependencies", []):
        source = dependency.get("source")
        target = dependency.get("target")
        if not source or not target:
            continue
        source_package = _module_to_package(source, depth)
        target_package = _module_to_package(target, depth)
        if source_package != target_package:
            edge_weights[(source_package, target_package)] += 1

    packages = sorted(node_counts, key=lambda package: node_counts[package], reverse=True)[:top_n]
    packages = sorted(packages)
    index = {package: position for position, package in enumerate(packages)}
    matrix = [[0 for _ in packages] for _ in packages]
    for (source, target), weight in edge_weights.items():
        if source in index and target in index:
            matrix[index[source]][index[target]] += weight
    return packages, matrix


def normalize_metrics(metrics_a: dict[str, float], metrics_b: dict[str, float], keys: list[str]) -> tuple[list[float], list[float]]:
    left: list[float] = []
    right: list[float] = []
    for key in keys:
        scale = max(metrics_a.get(key, 0.0), metrics_b.get(key, 0.0), 1e-9)
        left.append(metrics_a.get(key, 0.0) / scale)
        right.append(metrics_b.get(key, 0.0) / scale)
    return left, right


def radar_chart(output: Path, left_name: str, right_name: str, left_metrics: dict[str, float], right_metrics: dict[str, float]) -> None:
    labels = ["Complexité", "Maintainability", "CBO", "LCOM", "Halstead"]
    keys = ["Complexité moyenne", "Maintainability Index", "CBO", "LCOM", "Halstead"]
    left_values, right_values = normalize_metrics(left_metrics, right_metrics, keys)
    angles = [n / float(len(labels)) * 2 * math.pi for n in range(len(labels))]
    angles += angles[:1]
    left_values += left_values[:1]
    right_values += right_values[:1]

    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(angles, left_values, color="#1f77b4", linewidth=2, label=left_name)
    ax.fill(angles, left_values, color="#1f77b4", alpha=0.18)
    ax.plot(angles, right_values, color="#ff7f0e", linewidth=2, label=right_name)
    ax.fill(angles, right_values, color="#ff7f0e", alpha=0.18)
    ax.set_thetagrids([angle * 180 / math.pi for angle in angles[:-1]], labels)
    ax.set_ylim(0, 1.05)
    ax.set_title("Radar Chart des métriques normalisées")
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def bar_chart(output: Path, left_name: str, right_name: str, left_metrics: dict[str, float], right_metrics: dict[str, float]) -> None:
    metrics = [
        "Complexité moyenne",
        "Maintainability Index",
        "CBO",
        "LCOM",
        "Nombre de classes",
        "Nombre de modules",
        "Nombre de fonctions",
        "Halstead",
    ]
    fig, axes = plt.subplots(4, 2, figsize=(16, 14))
    axes_flat = list(axes.flat)
    for axis, metric in zip(axes_flat, metrics, strict=False):
        axis.bar([left_name, right_name], [left_metrics.get(metric, 0.0), right_metrics.get(metric, 0.0)], color=["#1f77b4", "#ff7f0e"])
        axis.set_title(metric)
        axis.tick_params(axis="x", rotation=20)
    for axis in axes_flat[len(metrics) :]:
        axis.axis("off")
    fig.suptitle("Bar Chart comparatif des métriques principales", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(output, dpi=200)
    plt.close(fig)


def boxplot_complexity(
    output: Path,
    left_name: str,
    right_name: str,
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
) -> None:
    left_values = [row["complexity"] for row in left_rows]
    right_values = [row["complexity"] for row in right_rows]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.boxplot([left_values, right_values], tick_labels=[left_name, right_name], showmeans=True)
    ax.set_title("Boxplot de la complexité cyclomatique")
    ax.set_ylabel("Complexité")
    sections = [
        f"{name}:\n{text}" for name, text in [(left_name, top_outliers_text(left_rows)), (right_name, top_outliers_text(right_rows))] if text
    ]
    if sections:
        ax.text(
            1.02, 0.98, "\n\n".join(sections), transform=ax.transAxes, fontsize=7, va="top", ha="left",
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
        )
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)


def heatmap_dependency(
    output: Path,
    left_name: str,
    right_name: str,
    left_arch: dict[str, Any],
    right_arch: dict[str, Any],
    package_depth: int | None = 1,
    top_n: int = 30,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for axis, name, architecture in zip(axes, [left_name, right_name], [left_arch, right_arch], strict=False):
        packages, matrix = repo_package_dependency_matrix(architecture, package_depth, top_n)
        if not packages:
            axis.set_axis_off()
            continue
        image = axis.imshow(matrix, cmap="Blues", aspect="auto")
        axis.set_title(f"Heatmap dépendances - {name}")
        axis.set_xticks(range(len(packages)))
        axis.set_xticklabels(packages, rotation=90, fontsize=7)
        axis.set_yticks(range(len(packages)))
        axis.set_yticklabels(packages, fontsize=7)
        fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)


def architecture_graph(
    output: Path,
    left_name: str,
    right_name: str,
    left_arch: dict[str, Any],
    right_arch: dict[str, Any],
    package_depth: int | None = 1,
    top_n: int = 30,
) -> None:
    try:
        import networkx as nx
    except ImportError:
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    for axis, name, architecture, color in zip(
        axes,
        [left_name, right_name],
        [left_arch, right_arch],
        ["#1f77b4", "#ff7f0e"],
        strict=False,
    ):
        packages, matrix = repo_package_dependency_matrix(architecture, package_depth, top_n)
        graph = nx.DiGraph()
        graph.add_nodes_from(packages)
        for source_index, source in enumerate(packages):
            for target_index, target in enumerate(packages):
                weight = matrix[source_index][target_index]
                if weight:
                    graph.add_edge(source, target, weight=weight)
        if graph.number_of_nodes() == 0:
            axis.set_axis_off()
            continue
        positions = nx.spring_layout(graph, seed=42)
        nx.draw_networkx(
            graph,
            positions,
            ax=axis,
            node_size=400,
            font_size=7,
            node_color=color,
            edge_color="#999999",
            arrows=True,
        )
        axis.set_title(f"Graphe d'architecture - {name}")
        axis.axis("off")
        cycle_groups = [sorted(group) for group in nx.strongly_connected_components(graph) if len(group) > 1]
        if cycle_groups:
            cycles_text = "Cycles de dependances:\n" + "\n".join(" <-> ".join(group) for group in cycle_groups[:5])
            axis.text(
                0.02, 0.02, cycles_text, transform=axis.transAxes, fontsize=6, va="bottom", ha="left",
                bbox=dict(boxstyle="round", facecolor="#fff3cd", edgecolor="#856404", alpha=0.9),
            )
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_comparison_bundle(
    output_dir: Path,
    left_name: str,
    right_name: str,
    left_pack: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    right_pack: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    package_depth: int | None = 1,
    top_n_packages: int = 30,
) -> None:
    if plt is None or pd is None:
        raise SystemExit(f"matplotlib and pandas are required: {OPTIONAL_ERROR}")
    output_dir.mkdir(parents=True, exist_ok=True)
    left_summary, left_radon, left_cbo, left_cohesion, left_arch = left_pack
    right_summary, right_radon, right_cbo, right_cohesion, right_arch = right_pack

    left_metrics = repo_summary_metrics(left_summary, left_radon, left_cbo, left_cohesion)
    right_metrics = repo_summary_metrics(right_summary, right_radon, right_cbo, right_cohesion)
    bar_chart(output_dir / "bar_chart.png", left_name, right_name, left_metrics, right_metrics)
    boxplot_complexity(
        output_dir / "boxplot_complexity.png",
        left_name,
        right_name,
        flatten_complexities_detailed(left_radon),
        flatten_complexities_detailed(right_radon),
    )
    radar_chart(output_dir / "radar_chart.png", left_name, right_name, left_metrics, right_metrics)
    heatmap_dependency(
        output_dir / "dependency_heatmap.png", left_name, right_name, left_arch, right_arch, package_depth, top_n_packages
    )
    architecture_graph(
        output_dir / "architecture_graph.png", left_name, right_name, left_arch, right_arch, package_depth, top_n_packages
    )


def summarize(data: dict[str, Any], label: str) -> dict[str, Any]:
    rows = data.get("packages") or data.get("files", [])
    line_key = "line_count" if data.get("packages") else "lines"
    class_key = "class_count" if data.get("packages") else "classes"
    function_key = "function_count" if data.get("packages") else "functions"
    return {
        "repository": label,
        "packages": len(rows),
        "lines": sum(item.get(line_key, 0) for item in rows),
        "classes": sum(item.get(class_key, 0) for item in rows),
        "functions": sum(item.get(function_key, 0) for item in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two repository summaries")
    parser.add_argument("--left", type=Path, default=None, help="First summary JSON/CSV")
    parser.add_argument("--right", type=Path, default=None, help="Second summary JSON/CSV")
    parser.add_argument("--left-repo", type=str, default=None, help="First repository URL or path")
    parser.add_argument("--left-branch", type=str, default=None, help="Branch for --left-repo")
    parser.add_argument(
        "--left-subpath",
        type=str,
        default=None,
        help="Subdirectory to analyze inside --left/--left-repo (e.g. 'hydromodpy' when comparing a package inside a monorepo)",
    )
    parser.add_argument("--right-repo", type=str, default=None, help="Second repository URL or path")
    parser.add_argument("--right-branch", type=str, default=None, help="Branch for --right-repo")
    parser.add_argument(
        "--right-subpath",
        type=str,
        default=None,
        help="Subdirectory to analyze inside --right/--right-repo (e.g. 'hydromodpy' when comparing a package inside a monorepo)",
    )
    parser.add_argument("--left-label", type=str, default=None, help="Manual label for the left side")
    parser.add_argument("--right-label", type=str, default=None, help="Manual label for the right side")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output")
    parser.add_argument("--chart", type=Path, default=None, help="Optional bar chart output")
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional directory for all charts")
    parser.add_argument(
        "--package-depth",
        type=int,
        default=1,
        help="Number of dotted segments used to group packages in the architecture graph/heatmap (1 = top-level package)",
    )
    parser.add_argument(
        "--top-n-packages",
        type=int,
        default=30,
        help="Maximum number of packages shown in the architecture graph/heatmap",
    )
    args = parser.parse_args()

    left_name = label_from_path_or_repo(args.left, args.left_repo, "left", args.left_label)
    right_name = label_from_path_or_repo(args.right, args.right_repo, "right", args.right_label)
    if left_name == right_name:
        left_name = f"{left_name} (left)"
        right_name = f"{right_name} (right)"

    left = summarize(
        load_or_summarize(args.left, args.left_repo, args.left_branch, "left", args.left_subpath),
        left_name,
    )
    right = summarize(
        load_or_summarize(args.right, args.right_repo, args.right_branch, "right", args.right_subpath),
        right_name,
    )
    result = {"left": left, "right": right}

    if args.output is None:
        print(json.dumps(result, indent=2))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.chart is not None:
        if plt is None or pd is None:
            raise SystemExit(f"matplotlib and pandas are required: {OPTIONAL_ERROR}")
        frame = pd.DataFrame([left, right]).set_index("repository")
        axes = frame[["packages", "lines", "classes", "functions"]].plot(kind="bar", figsize=(10, 6))
        axes.set_title("Repository comparison by package")
        axes.set_ylabel("Count")
        axes.figure.tight_layout()
        args.chart.parent.mkdir(parents=True, exist_ok=True)
        axes.figure.savefig(args.chart, dpi=200)
        plt.close(axes.figure)

    if args.output_dir is not None:
        left_pack = load_metrics(args.left, args.left_repo, args.left_branch, args.left_subpath)
        right_pack = load_metrics(args.right, args.right_repo, args.right_branch, args.right_subpath)
        write_comparison_bundle(
            args.output_dir, left_name, right_name, left_pack, right_pack, args.package_depth, args.top_n_packages
        )


if __name__ == "__main__":
    main()
