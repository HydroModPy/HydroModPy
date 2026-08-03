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
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".csv":
        if pd is None:
            raise SystemExit(f"pandas is required: {OPTIONAL_ERROR}")
        frame = pd.read_csv(path)
        return {"files": frame.to_dict(orient="records")}
    raise SystemExit(f"Unsupported summary format: {path}")


def load_or_summarize(
    path: Path | None,
    repo: str | None,
    branch: str | None,
    label: str,
) -> dict[str, Any]:
    if path is not None:
        return load_summary(path)
    if repo is not None:
        with resolve_repository_root(None, repo, branch) as root:
            return summarize_repository(root)
    raise SystemExit(f"Missing input for {label}: provide either a summary file or a repository")


def label_from_path_or_repo(path: Path | None, repo: str | None, default: str) -> str:
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
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if path is not None:
        if path.is_dir():
            with resolve_repository_root(path, None, None) as root:
                return (
                    summarize_repository(root),
                    compute_radon_metrics(root),
                    compute_cbo(root),
                    compute_cohesion(root),
                    collect_architecture(root),
                )
        raise SystemExit("--output-dir requires --left-repo/--right-repo or repository directories, not summary files")
    if repo is not None:
        with resolve_repository_root(None, repo, branch) as root:
            return (
                summarize_repository(root),
                compute_radon_metrics(root),
                compute_cbo(root),
                compute_cohesion(root),
                collect_architecture(root),
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


def halstead_values(radon: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for file_info in radon.get("files", []):
        halstead = file_info.get("halstead") or {}
        volume = halstead.get("volume")
        if isinstance(volume, (int, float)):
            values.append(float(volume))
    return values


def repo_summary_metrics(summary: dict[str, Any], radon: dict[str, Any], cbo: dict[str, Any], cohesion: dict[str, Any]) -> dict[str, float]:
    files = summary.get("files", [])
    complexity_values = flatten_complexities(radon)
    maintainability_values = file_level_metric(radon.get("files", []), "maintainability_index")
    cbo_values = file_level_metric(cbo.get("files", []), "cbo")
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


def repo_dependency_matrix(architecture: dict[str, Any]) -> tuple[list[str], list[list[int]]]:
    modules = sorted(module_info["module"] for module_info in architecture.get("modules", []))
    index = {module: position for position, module in enumerate(modules)}
    matrix = [[0 for _ in modules] for _ in modules]
    for dependency in architecture.get("dependencies", []):
        source = dependency.get("source")
        target = dependency.get("target")
        if source in index and target in index:
            matrix[index[source]][index[target]] += 1
    return modules, matrix


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


def boxplot_complexity(output: Path, left_name: str, right_name: str, left_values: list[float], right_values: list[float]) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.boxplot([left_values, right_values], labels=[left_name, right_name], showmeans=True)
    ax.set_title("Boxplot de la complexité cyclomatique")
    ax.set_ylabel("Complexité")
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def heatmap_dependency(output: Path, left_name: str, right_name: str, left_arch: dict[str, Any], right_arch: dict[str, Any]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for axis, name, architecture in zip(axes, [left_name, right_name], [left_arch, right_arch], strict=False):
        modules, matrix = repo_dependency_matrix(architecture)
        if not modules:
            axis.set_axis_off()
            continue
        image = axis.imshow(matrix, cmap="Blues", aspect="auto")
        axis.set_title(f"Heatmap dépendances - {name}")
        axis.set_xticks(range(len(modules)))
        axis.set_xticklabels(modules, rotation=90, fontsize=6)
        axis.set_yticks(range(len(modules)))
        axis.set_yticklabels(modules, fontsize=6)
        fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def architecture_graph(output: Path, left_name: str, right_name: str, left_arch: dict[str, Any], right_arch: dict[str, Any]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    for axis, name, architecture, color in zip(
        axes,
        [left_name, right_name],
        [left_arch, right_arch],
        ["#1f77b4", "#ff7f0e"],
        strict=False,
    ):
        graph = __import__("networkx").DiGraph()
        for module_info in architecture.get("modules", []):
            graph.add_node(module_info["module"])
        for dependency in architecture.get("dependencies", []):
            graph.add_edge(dependency["source"], dependency["target"])
        if graph.number_of_nodes() == 0:
            axis.set_axis_off()
            continue
        positions = __import__("networkx").spring_layout(graph, seed=42)
        __import__("networkx").draw_networkx(
            graph,
            positions,
            ax=axis,
            node_size=300,
            font_size=6,
            node_color=color,
            edge_color="#999999",
            arrows=True,
        )
        axis.set_title(f"Graphe d'architecture - {name}")
        axis.axis("off")
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def write_comparison_bundle(
    output_dir: Path,
    left_name: str,
    right_name: str,
    left_pack: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
    right_pack: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
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
        flatten_complexities(left_radon),
        flatten_complexities(right_radon),
    )
    radar_chart(output_dir / "radar_chart.png", left_name, right_name, left_metrics, right_metrics)
    heatmap_dependency(output_dir / "dependency_heatmap.png", left_name, right_name, left_arch, right_arch)
    architecture_graph(output_dir / "architecture_graph.png", left_name, right_name, left_arch, right_arch)


def summarize(data: dict[str, Any], label: str) -> dict[str, Any]:
    files = data.get("files", [])
    return {
        "repository": label,
        "files": len(files),
        "lines": sum(item.get("lines", 0) for item in files),
        "classes": sum(item.get("classes", 0) for item in files),
        "functions": sum(item.get("functions", 0) for item in files),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two repository summaries")
    parser.add_argument("--left", type=Path, default=None, help="First summary JSON/CSV")
    parser.add_argument("--right", type=Path, default=None, help="Second summary JSON/CSV")
    parser.add_argument("--left-repo", type=str, default=None, help="First repository URL or path")
    parser.add_argument("--left-branch", type=str, default=None, help="Branch for --left-repo")
    parser.add_argument("--right-repo", type=str, default=None, help="Second repository URL or path")
    parser.add_argument("--right-branch", type=str, default=None, help="Branch for --right-repo")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output")
    parser.add_argument("--chart", type=Path, default=None, help="Optional bar chart output")
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional directory for all charts")
    args = parser.parse_args()

    left_name = label_from_path_or_repo(args.left, args.left_repo, "left")
    right_name = label_from_path_or_repo(args.right, args.right_repo, "right")

    left = summarize(
        load_or_summarize(args.left, args.left_repo, args.left_branch, "left"),
        left_name,
    )
    right = summarize(
        load_or_summarize(args.right, args.right_repo, args.right_branch, "right"),
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
        axes = frame[["files", "lines", "classes", "functions"]].plot(kind="bar", figsize=(10, 6))
        axes.set_title("Repository comparison")
        axes.set_ylabel("Count")
        axes.figure.tight_layout()
        args.chart.parent.mkdir(parents=True, exist_ok=True)
        axes.figure.savefig(args.chart, dpi=200)
        plt.close(axes.figure)

    if args.output_dir is not None:
        left_pack = load_metrics(args.left, args.left_repo, args.left_branch)
        right_pack = load_metrics(args.right, args.right_repo, args.right_branch)
        write_comparison_bundle(args.output_dir, left_name, right_name, left_pack, right_pack)


if __name__ == "__main__":
    main()
