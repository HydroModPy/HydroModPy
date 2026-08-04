from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import pandas as pd
except ImportError:  # pragma: no cover - optional dependency
    pd = None

from evaluation._utils import resolve_repository_root, safe_mkdir
from evaluation.cohesion import compute_cohesion
from evaluation.coupling import compute_cbo
from evaluation.extract_architecture import collect_architecture, save_graph
from evaluation.generate_report import build_frames, build_package_dependency_frame, write_charts, write_excel
from evaluation.radon_metrics import compute_radon_metrics
from evaluation.repository_summary import summarize_repository


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_architecture_excel(
    output_path: Path,
    summary_frame: "pd.DataFrame",
    architecture_data: dict,
    dependency_frame: "pd.DataFrame",
) -> None:
    if pd is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    modules_frame = pd.DataFrame(architecture_data.get("modules", []))
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_frame.to_excel(writer, sheet_name="packages", index=False)
        modules_frame.to_excel(writer, sheet_name="modules", index=False)
        dependency_frame.to_excel(writer, sheet_name="dependencies", index=False)


def build_package_graph(
    architecture_data: dict,
    summary_frame: "pd.DataFrame",
    top_n: int = 8,
    min_edge_weight: int = 2,
    max_edges: int = 20,
):
    dependency_frame = build_package_dependency_frame(architecture_data)
    if dependency_frame.empty:
        return None, dependency_frame

    if not summary_frame.empty and "package" in summary_frame.columns:
        top_packages = (
            summary_frame.sort_values("line_count", ascending=False)
            .head(top_n)["package"]
            .dropna()
            .tolist()
        )
        filtered = dependency_frame[
            dependency_frame["source"].isin(top_packages)
            & dependency_frame["target"].isin(top_packages)
        ]
        if "weight" in filtered.columns:
            filtered = filtered[filtered["weight"] >= min_edge_weight]
        if not filtered.empty:
            dependency_frame = filtered.sort_values("weight", ascending=False).head(max_edges)
        else:
            fallback = dependency_frame.copy()
            if "weight" in fallback.columns:
                fallback = fallback.sort_values("weight", ascending=False).head(max_edges)
            dependency_frame = fallback

    try:
        import networkx as nx
    except ImportError:
        return None, dependency_frame

    graph = nx.DiGraph()
    if not summary_frame.empty and "package" in summary_frame.columns:
        top_packages = (
            summary_frame.sort_values("line_count", ascending=False)
            .head(top_n)["package"]
            .dropna()
            .tolist()
        )
        graph.add_nodes_from(top_packages)
    for _, edge in dependency_frame.iterrows():
        graph.add_edge(edge["source"], edge["target"], weight=int(edge.get("weight", 1)))
    return graph, dependency_frame


def run_for_root(root: Path, output_dir: Path, excel_path: Path | None) -> None:
    raw_dir = safe_mkdir(output_dir / "raw")
    report_dir = safe_mkdir(output_dir / "report")

    summary = summarize_repository(root)
    radon = compute_radon_metrics(root)
    coupling = compute_cbo(root)
    cohesion = compute_cohesion(root)
    architecture = collect_architecture(root)
    architecture_data = architecture.get("data", architecture)

    write_json(raw_dir / "summary.json", summary)
    write_json(raw_dir / "radon.json", radon)
    write_json(raw_dir / "coupling.json", coupling)
    write_json(raw_dir / "cohesion.json", cohesion)
    write_json(raw_dir / "architecture.json", architecture_data)

    frames = None
    if pd is not None:
        frames = build_frames(raw_dir)
        summary_frame = frames[0]
        package_graph, dependency_frame = build_package_graph(architecture_data, summary_frame)
        if package_graph is not None:
            # package_graph is already aggregated by build_package_graph()
            # (top-N packages) — don't have save_graph() collapse it again.
            save_graph(package_graph, raw_dir / "architecture_graph.png", package_depth=None, node_is_module=False)
        else:
            save_graph(architecture.get("graph"), raw_dir / "architecture_graph.png")
        if excel_path is not None:
            write_excel(excel_path, frames)
        write_architecture_excel(output_dir / "architecture.xlsx", summary_frame, architecture_data, dependency_frame)
        for name, frame in zip(["summary", "radon", "coupling", "cohesion", "architecture"], frames, strict=False):
            frame.to_csv(report_dir / f"{name}.csv", index=False)
        write_charts(report_dir / "charts", frames)
    else:
        save_graph(architecture.get("graph"), raw_dir / "architecture_graph.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run complete repository evaluation")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repo", type=str)
    parser.add_argument("--branch", type=str)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--excel", type=Path)
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        excel_path = args.excel.expanduser().resolve() if args.excel is not None else output_dir / "evaluation.xlsx"
        run_for_root(root, output_dir, excel_path)


if __name__ == "__main__":
    main()
