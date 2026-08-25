from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - optional dependency
    pd = None
    PANDAS_ERROR = exc
else:
    PANDAS_ERROR = None

try:
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - optional dependency
    plt = None
    MPL_ERROR = exc
else:
    MPL_ERROR = None

from evaluation._utils import resolve_repository_root
from evaluation.cohesion import compute_cohesion
from evaluation.coupling import compute_cbo
from evaluation.extract_architecture import collect_architecture
from evaluation.radon_metrics import compute_radon_metrics
from evaluation.repository_summary import summarize_repository


TOP_N_PACKAGES = 15
TOP_N_MODULES = 20
TOP_N_BOXPLOT_PACKAGES = 10
PACKAGE_GROUP_DEPTH = 1


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def package_summary_frame(summary: dict[str, Any]) -> "pd.DataFrame":
    packages = summary.get("packages") or []
    if packages:
        return pd.DataFrame(packages)

    files = pd.DataFrame(summary.get("files", []))
    if files.empty:
        return pd.DataFrame()

    if "package" not in files.columns:
        files["package"] = files["module"].apply(lambda name: name.rsplit(".", 1)[0] if "." in name else name)

    grouped = files.groupby("package", dropna=False).agg(
        file_count=("path", "count"),
        module_count=("module", "nunique"),
        public_module_count=("public", "sum") if "public" in files.columns else ("module", "count"),
        class_count=("classes", "sum") if "classes" in files.columns else ("module", "count"),
        method_count=("methods", "sum") if "methods" in files.columns else ("module", "count"),
        function_count=("functions", "sum") if "functions" in files.columns else ("module", "count"),
        line_count=("lines", "sum") if "lines" in files.columns else ("module", "count"),
    )
    return grouped.reset_index()


def top_modules_frame(summary: dict[str, Any]) -> "pd.DataFrame":
    top_modules = summary.get("top_modules") or []
    if top_modules:
        return pd.DataFrame(top_modules)

    files = pd.DataFrame(summary.get("files", []))
    if files.empty:
        return pd.DataFrame()
    if "public" in files.columns:
        files = files[files["public"]]
    if files.empty:
        files = pd.DataFrame(summary.get("files", []))
    return files.sort_values(["lines", "module"], ascending=[False, True]).head(TOP_N_MODULES)


def flatten_coupling(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_info in data.get("files", []):
        module = file_info.get("module")
        package = file_info.get("package")
        public = file_info.get("public")
        for cls in file_info.get("classes", []):
            rows.append(
                {
                    "module": module,
                    "package": package,
                    "public": public,
                    "path": file_info.get("path"),
                    **cls,
                }
            )
    return rows


def flatten_cohesion(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_info in data.get("files", []):
        module = file_info.get("module")
        package = file_info.get("package")
        public = file_info.get("public")
        for cls in file_info.get("classes", []):
            rows.append(
                {
                    "module": module,
                    "package": package,
                    "public": public,
                    "path": file_info.get("path"),
                    **cls,
                }
            )
    return rows


def _module_to_package(module: str, depth: int | None = None) -> str:
    package = module.rsplit(".", 1)[0] if "." in module else module
    if depth is not None:
        package = ".".join(package.split(".")[:depth]) or package
    return package


def build_package_dependency_frame(architecture: "pd.DataFrame | dict[str, Any]", depth: int | None = None) -> "pd.DataFrame":
    if isinstance(architecture, dict):
        architecture = pd.DataFrame(architecture.get("modules", []))
    if architecture.empty or "module" not in architecture.columns:
        return pd.DataFrame()

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for _, module_info in architecture.iterrows():
        source_module = module_info.get("module")
        if not source_module:
            continue
        source_package = _module_to_package(source_module, depth)
        for dependency in module_info.get("internal_dependencies") or []:
            target_package = _module_to_package(dependency, depth)
            if source_package and target_package and source_package != target_package:
                edge_weights[(source_package, target_package)] += 1

    rows = [
        {"source": source, "target": target, "weight": weight}
        for (source, target), weight in sorted(edge_weights.items())
    ]
    return pd.DataFrame(rows)


def public_only(frame: "pd.DataFrame") -> "pd.DataFrame":
    if frame.empty:
        return frame
    if "public" in frame.columns:
        public_frame = frame[frame["public"].fillna(False)]
        if not public_frame.empty:
            return public_frame
    return frame


def package_group_column(frame: "pd.DataFrame", depth: int, source_col: str = "package") -> "pd.Series":
    if frame.empty or source_col not in frame.columns:
        return pd.Series(dtype=object)
    return frame[source_col].fillna("").astype(str).apply(lambda value: ".".join(value.split(".")[:depth]) or value)


def select_package_order(counts: "pd.Series", top_n: int, pinned: list[str]) -> list[str]:
    ordered = counts.sort_values(ascending=False)
    selected = list(ordered.head(top_n).index)
    for package in pinned:
        if package in ordered.index and package not in selected:
            selected.append(package)
    return selected


def dependency_cycles_text(graph: Any, n: int = 5) -> str:
    # Strongly connected components with more than one node are exactly the
    # packages caught in an import cycle. This is O(V+E) via Tarjan's
    # algorithm, unlike enumerating every simple cycle which can blow up
    # combinatorially on a real dependency graph.
    import networkx as nx

    cycle_groups = [sorted(group) for group in nx.strongly_connected_components(graph) if len(group) > 1]
    if not cycle_groups:
        return ""
    lines = [" <-> ".join(group) for group in cycle_groups[:n]]
    return "Cycles de dependances:\n" + "\n".join(lines)


def top_outliers_text(
    frame: "pd.DataFrame",
    value_col: str,
    label_cols: list[str],
    n: int = 5,
    ascending: bool = False,
    heading: str = "Valeurs extremes:",
) -> str:
    if frame.empty or value_col not in frame.columns:
        return ""
    subset = frame.dropna(subset=[value_col])
    if subset.empty:
        return ""
    subset = subset.nsmallest(n, value_col) if ascending else subset.nlargest(n, value_col)
    lines: list[str] = []
    for _, row in subset.iterrows():
        label = "::".join(str(row[col]) for col in label_cols if col in row and pd.notna(row[col]))
        lines.append(f"{label} = {row[value_col]:.1f}")
    return f"{heading}\n" + "\n".join(lines)


def explode_complexity_frame(radon: "pd.DataFrame") -> "pd.DataFrame":
    if radon.empty or "complexity" not in radon.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, row in radon.iterrows():
        for block in row.get("complexity", []) or []:
            complexity = block.get("complexity")
            if isinstance(complexity, (int, float)):
                rows.append(
                    {
                        "module": row.get("module"),
                        "package": row.get("package"),
                        "public": row.get("public", False),
                        "path": row.get("path"),
                        "name": block.get("name"),
                        "complexity": float(complexity),
                    }
                )
    return pd.DataFrame(rows)


_KIND_COLORS = {
    "business-logic": "#d62728",
    "facade": "#1f77b4",
    "protocol": "#7f7f7f",
    "dataclass": "#7f7f7f",
    "model": "#7f7f7f",
    "mixin": "#9467bd",
}


def write_afferent_efferent_scatter(coupling: "pd.DataFrame", output_path: Path) -> None:
    """Plot outgoing (Ce) vs incoming (Ca) coupling, colored by class kind.

    A facade/orchestrator is expected to land in the bottom-right (high Ce,
    low Ca) -- it deliberately depends on many collaborators so nothing else
    has to. A class in the top-right (high on both axes) is a stronger
    coupling-problem signal than either number alone: many things call it
    *and* it depends on many things.
    """
    data = coupling.dropna(subset=["efferent_coupling", "afferent_coupling"])
    if data.empty:
        return

    kinds = data["kind"] if "kind" in data.columns else pd.Series("business-logic", index=data.index)
    fig, ax = plt.subplots(figsize=(11, 8))
    for kind, group in data.groupby(kinds):
        ax.scatter(
            group["efferent_coupling"],
            group["afferent_coupling"],
            s=28,
            alpha=0.65,
            label=str(kind),
            color=_KIND_COLORS.get(str(kind), "#333333"),
        )

    # Every dot is a class, but labeling all of them would be unreadable, so
    # only the ones that stand out on at least one axis are named: highest
    # Ce alone (big facades/orchestrators), highest Ca alone (heavily reused
    # types), and highest combined score (the rarer, more interesting case
    # of a class that is both -- see the docstring).
    risk = data.assign(risk_score=data["efferent_coupling"] + data["afferent_coupling"] * 3)
    notable = pd.concat(
        [
            data.nlargest(8, "efferent_coupling"),
            data.nlargest(8, "afferent_coupling"),
            risk.nlargest(8, "risk_score"),
        ]
    ).drop_duplicates(subset=["module", "class"] if "module" in data.columns else ["class"])

    for _, row in notable.iterrows():
        ax.annotate(
            str(row.get("class", "")),
            (row["efferent_coupling"], row["afferent_coupling"]),
            fontsize=6.5,
            xytext=(4, 4),
            textcoords="offset points",
        )

    label_cols = ["module", "class"] if "module" in data.columns else ["class"]
    legend_lines = [
        f"{'::'.join(str(row[col]) for col in label_cols if col in row)} "
        f"(Ce={int(row['efferent_coupling'])}, Ca={int(row['afferent_coupling'])})"
        for _, row in notable.sort_values("efferent_coupling", ascending=False).head(15).iterrows()
    ]
    if legend_lines:
        ax.text(
            1.02, 0.98, "Classes notables:\n" + "\n".join(legend_lines),
            transform=ax.transAxes, fontsize=6.5, va="top", ha="left",
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
        )

    ax.set_xlabel("Couplage sortant (Ce) -- ce dont la classe depend")
    ax.set_ylabel("Couplage entrant (Ca) -- ce qui depend de la classe")
    ax.set_title("Couplage entrant vs sortant par classe")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(True, ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_excel(output_path: Path, frames: tuple[Any, ...]) -> None:
    if pd is None:
        raise SystemExit(f"pandas is required: {PANDAS_ERROR}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sheet_names = ["summary", "radon", "coupling", "cohesion", "architecture"]
        for sheet_name, frame in zip(sheet_names, frames, strict=False):
            frame.to_excel(writer, sheet_name=sheet_name, index=False)


def write_charts(
    output_dir: Path,
    frames: tuple[Any, ...],
    package_depth: int = PACKAGE_GROUP_DEPTH,
    pinned_packages: list[str] | None = None,
) -> None:
    if plt is None or pd is None:
        return

    pinned_packages = pinned_packages or []
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, radon, coupling, cohesion, architecture = frames

    if not summary.empty and "package" in summary.columns:
        summary_grouped = summary.copy()
        summary_grouped["package_group"] = package_group_column(summary_grouped, package_depth)
        columns = [col for col in ["line_count", "class_count", "function_count"] if col in summary_grouped.columns]
        if columns:
            grouped = summary_grouped.groupby("package_group", as_index=True)[columns].sum()
            rank_col = "line_count" if "line_count" in columns else columns[0]
            order = select_package_order(grouped[rank_col], TOP_N_PACKAGES, pinned_packages)
            top_packages = grouped.reindex(order)
            ax = top_packages[columns].plot(kind="bar", figsize=(14, 7))
            ax.set_title("Top packages by size")
            ax.set_xlabel("Package")
            ax.set_ylabel("Count")
            plt.tight_layout()
            plt.savefig(output_dir / "summary.png", dpi=200)
            plt.close()

        top_modules = summary.attrs.get("top_modules", pd.DataFrame())
        if not top_modules.empty and "lines" in top_modules.columns and "module" in top_modules.columns:
            ax = top_modules.set_index("module")["lines"].plot(kind="bar", figsize=(14, 7))
            ax.set_title("Top public modules by lines")
            ax.set_xlabel("Module")
            ax.set_ylabel("LOC")
            plt.tight_layout()
            plt.savefig(output_dir / "top_modules.png", dpi=200)
            plt.close()

    if not radon.empty:
        complexity = explode_complexity_frame(radon)
        if not complexity.empty:
            ax = complexity["complexity"].plot(kind="hist", bins=20, figsize=(10, 6), title="Cyclomatic complexity distribution")
            ax.set_xlabel("Complexity")
            outliers_text = top_outliers_text(complexity, "complexity", ["module", "name"])
            if outliers_text:
                ax.text(
                    0.98, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="right",
                    bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                )
            plt.tight_layout()
            plt.savefig(output_dir / "complexity_distribution.png", dpi=200)
            plt.close()

            complexity["package_group"] = package_group_column(complexity, package_depth)
            package_counts = complexity.groupby("package_group").size()
            package_order = select_package_order(package_counts, TOP_N_BOXPLOT_PACKAGES, pinned_packages)
            if package_order:
                data = [complexity.loc[complexity["package_group"] == package, "complexity"].dropna().tolist() for package in package_order]
                fig, ax = plt.subplots(figsize=(14, 7))
                ax.boxplot(data, tick_labels=package_order, showmeans=True)
                ax.set_title("Cyclomatic complexity by package")
                ax.set_ylabel("Complexity")
                ax.tick_params(axis="x", rotation=30)
                complexity_subset = complexity[complexity["package_group"].isin(package_order)]
                outliers_text = top_outliers_text(complexity_subset, "complexity", ["module", "name"])
                if outliers_text:
                    ax.text(
                        1.02, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                    )
                plt.tight_layout()
                plt.savefig(output_dir / "complexity_boxplot.png", dpi=200, bbox_inches="tight")
                plt.close(fig)

        if "maintainability_index" in radon.columns:
            series = radon["maintainability_index"].dropna()
            if not series.empty:
                ax = series.plot(kind="hist", bins=20, figsize=(10, 6), title="Maintainability Index distribution")
                ax.set_xlabel("Maintainability Index")
                outliers_text = top_outliers_text(
                    radon, "maintainability_index", ["module"], ascending=True, heading="Pires valeurs (MI bas):"
                )
                if outliers_text:
                    ax.text(
                        0.98, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="right",
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                    )
                plt.tight_layout()
                plt.savefig(output_dir / "maintainability.png", dpi=200)
                plt.close()

    if not coupling.empty and "cbo" in coupling.columns:
        coupling = public_only(coupling).copy()
        cbo_values = coupling["cbo"].dropna()
        if not cbo_values.empty:
            ax = cbo_values.plot(kind="hist", bins=20, figsize=(10, 6), title="CBO distribution")
            ax.set_xlabel("CBO")
            outliers_text = top_outliers_text(coupling, "cbo", ["module", "class"])
            if outliers_text:
                ax.text(
                    0.98, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="right",
                    bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                )
            plt.tight_layout()
            plt.savefig(output_dir / "coupling_distribution.png", dpi=200)
            plt.close()

        if {"efferent_coupling", "afferent_coupling"}.issubset(coupling.columns):
            write_afferent_efferent_scatter(coupling, output_dir / "coupling_afferent_vs_efferent.png")

        if "kind" in coupling.columns:
            coupling_ranked = coupling[coupling["kind"] == "business-logic"]
            title_suffix = " (business-logic classes only)"
        else:
            coupling_ranked = coupling
            title_suffix = ""
        if not coupling_ranked.empty:
            coupling_ranked = coupling_ranked.copy()
            coupling_ranked["package_group"] = package_group_column(coupling_ranked, package_depth)
            packages = coupling_ranked.groupby("package_group").size()
            order = select_package_order(packages, TOP_N_BOXPLOT_PACKAGES, pinned_packages)
            if order:
                data = [
                    coupling_ranked.loc[coupling_ranked["package_group"] == package, "cbo"].dropna().tolist()
                    for package in order
                ]
                fig, ax = plt.subplots(figsize=(14, 7))
                ax.boxplot(data, tick_labels=order, showmeans=True)
                ax.set_title(f"CBO by package{title_suffix}")
                ax.set_ylabel("CBO")
                ax.tick_params(axis="x", rotation=30)
                coupling_subset = coupling_ranked[coupling_ranked["package_group"].isin(order)]
                outliers_text = top_outliers_text(coupling_subset, "cbo", ["module", "class"])
                if outliers_text:
                    ax.text(
                        1.02, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                    )
                plt.tight_layout()
                plt.savefig(output_dir / "coupling_boxplot.png", dpi=200, bbox_inches="tight")
                plt.close(fig)

    if not cohesion.empty and "lcom" in cohesion.columns:
        cohesion = public_only(cohesion).copy()
        lcom_values = cohesion["lcom"].dropna()
        if not lcom_values.empty:
            ax = lcom_values.plot(kind="hist", bins=20, figsize=(10, 6), title="LCOM distribution")
            ax.set_xlabel("LCOM")
            outliers_text = top_outliers_text(cohesion, "lcom", ["module", "class"])
            if outliers_text:
                ax.text(
                    0.98, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="right",
                    bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                )
            plt.tight_layout()
            plt.savefig(output_dir / "cohesion_distribution.png", dpi=200)
            plt.close()

            cohesion["package_group"] = package_group_column(cohesion, package_depth)
            packages = cohesion.groupby("package_group").size()
            order = select_package_order(packages, TOP_N_BOXPLOT_PACKAGES, pinned_packages)
            if order:
                data = [cohesion.loc[cohesion["package_group"] == package, "lcom"].dropna().tolist() for package in order]
                fig, ax = plt.subplots(figsize=(14, 7))
                ax.boxplot(data, tick_labels=order, showmeans=True)
                # "lcom" is already None for dataclass/model/protocol/mixin/facade
                # classes (see cohesion.py), so dropna() above already limits this
                # chart to business-logic classes -- the only ones LCOM applies to.
                ax.set_title("LCOM by package (business-logic classes only)")
                ax.set_ylabel("LCOM")
                ax.tick_params(axis="x", rotation=30)
                cohesion_subset = cohesion[cohesion["package_group"].isin(order)]
                outliers_text = top_outliers_text(cohesion_subset, "lcom", ["module", "class"])
                if outliers_text:
                    ax.text(
                        1.02, 0.98, outliers_text, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                        bbox=dict(boxstyle="round", facecolor="white", edgecolor="gray", alpha=0.9),
                    )
                plt.tight_layout()
                plt.savefig(output_dir / "cohesion_boxplot.png", dpi=200, bbox_inches="tight")
                plt.close(fig)

    architecture_graph = build_package_dependency_frame(architecture, package_depth)
    if not architecture_graph.empty:
        packages = sorted(set(architecture_graph["source"]).union(set(architecture_graph["target"])))
        index = {package: i for i, package in enumerate(packages)}
        matrix = [[0 for _ in packages] for _ in packages]
        for _, edge in architecture_graph.iterrows():
            matrix[index[edge["source"]]][index[edge["target"]]] += int(edge["weight"])

        fig, ax = plt.subplots(figsize=(12, 10))
        image = ax.imshow(matrix, cmap="Blues", aspect="auto")
        ax.set_title("Package dependency heatmap")
        ax.set_xticks(range(len(packages)))
        ax.set_yticks(range(len(packages)))
        ax.set_xticklabels(packages, rotation=90, fontsize=7)
        ax.set_yticklabels(packages, fontsize=7)
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        plt.tight_layout()
        plt.savefig(output_dir / "architecture_package_heatmap.png", dpi=200)
        plt.close(fig)

        try:
            import networkx as nx
        except ImportError:
            return

        graph = nx.DiGraph()
        for _, edge in architecture_graph.iterrows():
            graph.add_edge(edge["source"], edge["target"], weight=edge["weight"])
        if graph.number_of_nodes() > 0:
            fig, ax = plt.subplots(figsize=(14, 10))
            positions = nx.spring_layout(graph, seed=42)
            nx.draw_networkx(
                graph,
                positions,
                ax=ax,
                node_size=400,
                font_size=7,
                arrows=True,
                edge_color="#888888",
            )
            ax.set_title("Package architecture graph")
            ax.axis("off")
            cycles_text = dependency_cycles_text(graph)
            if cycles_text:
                ax.text(
                    1.02, 0.98, cycles_text, transform=ax.transAxes, fontsize=7, va="top", ha="left",
                    bbox=dict(boxstyle="round", facecolor="#fff3cd", edgecolor="#856404", alpha=0.9),
                )
            plt.tight_layout()
            plt.savefig(output_dir / "architecture_package_graph.png", dpi=200, bbox_inches="tight")
            plt.close(fig)


def _build_frames(summary: dict[str, Any], radon: dict[str, Any], coupling: dict[str, Any], cohesion: dict[str, Any], architecture: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    summary_frame = package_summary_frame(summary)
    summary_frame.attrs["top_modules"] = top_modules_frame(summary)
    return (
        summary_frame,
        pd.DataFrame(radon.get("files", [])),
        pd.DataFrame(flatten_coupling(coupling)),
        pd.DataFrame(flatten_cohesion(cohesion)),
        pd.DataFrame(architecture.get("modules", [])),
    )


def build_frames_from_repo(root: Path):
    summary = summarize_repository(root)
    radon = compute_radon_metrics(root)
    coupling = compute_cbo(root)
    cohesion = compute_cohesion(root)
    architecture = collect_architecture(root)
    architecture = architecture.get("data", architecture)
    return _build_frames(summary, radon, coupling, cohesion, architecture)


def build_frames(input_dir: Path):
    if pd is None:
        raise SystemExit(f"pandas is required: {PANDAS_ERROR}")

    summary = load_json(input_dir / "summary.json")
    radon = load_json(input_dir / "radon.json")
    coupling = load_json(input_dir / "coupling.json")
    cohesion = load_json(input_dir / "cohesion.json")
    architecture = load_json(input_dir / "architecture.json")
    return _build_frames(summary, radon, coupling, cohesion, architecture)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate quality report")
    parser.add_argument("--repo", type=str)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--excel", type=Path, default=None)
    parser.add_argument(
        "--package-depth",
        type=int,
        default=PACKAGE_GROUP_DEPTH,
        help="Number of dotted segments used to group packages in charts (1 = top-level package)",
    )
    parser.add_argument(
        "--pin-package",
        action="append",
        default=None,
        help="Package (at --package-depth granularity) to always include in the top-N charts, can be repeated",
    )
    args = parser.parse_args()

    if pd is None:
        raise SystemExit(f"pandas is required: {PANDAS_ERROR}")

    with resolve_repository_root(None, args.repo, None) as root:
        frames = build_frames_from_repo(root)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    names = ["summary", "radon", "coupling", "cohesion", "architecture"]
    for name, frame in zip(names, frames, strict=False):
        frame.to_csv(args.output_dir / f"{name}.csv", index=False)

    excel_path = args.excel if args.excel is not None else args.output_dir / "evaluation.xlsx"
    write_excel(excel_path, frames)
    write_charts(args.output_dir / "charts", frames, args.package_depth, args.pin_package)


if __name__ == "__main__":
    main()
