from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import sys

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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_frames_from_repo(root: Path) -> tuple[Any, Any, Any, Any, Any]:
    summary = summarize_repository(root)
    radon = compute_radon_metrics(root)
    coupling = compute_cbo(root)
    cohesion = compute_cohesion(root)
    architecture = collect_architecture(root)

    summary_frame = pd.DataFrame(summary.get("files", []))
    radon_frame = pd.DataFrame(radon.get("files", []))
    coupling_frame = pd.DataFrame(coupling.get("files", []))
    cohesion_frame = pd.DataFrame(
        [
            {"path": file_info.get("path"), **class_info}
            for file_info in cohesion.get("files", [])
            for class_info in file_info.get("classes", [])
        ]
    )
    architecture_frame = pd.DataFrame(architecture.get("modules", []))
    return summary_frame, radon_frame, coupling_frame, cohesion_frame, architecture_frame


def build_frames(input_dir: Path) -> tuple[Any, Any, Any, Any, Any]:
    if pd is None:
        raise SystemExit(f"pandas is required: {PANDAS_ERROR}")
    summary = load_json(input_dir / "summary.json") if (input_dir / "summary.json").exists() else {}
    radon = load_json(input_dir / "radon.json") if (input_dir / "radon.json").exists() else {}
    coupling = load_json(input_dir / "coupling.json") if (input_dir / "coupling.json").exists() else {}
    cohesion = load_json(input_dir / "cohesion.json") if (input_dir / "cohesion.json").exists() else {}
    architecture = load_json(input_dir / "architecture.json") if (input_dir / "architecture.json").exists() else {}

    summary_frame = pd.DataFrame(summary.get("files", []))
    radon_frame = pd.DataFrame(radon.get("files", []))
    coupling_frame = pd.DataFrame(coupling.get("files", []))
    cohesion_frame = pd.DataFrame(
        [
            {"path": file_info.get("path"), **class_info}
            for file_info in cohesion.get("files", [])
            for class_info in file_info.get("classes", [])
        ]
    )
    architecture_frame = pd.DataFrame(architecture.get("modules", []))
    return summary_frame, radon_frame, coupling_frame, cohesion_frame, architecture_frame


def write_excel(output_path: Path, frames: tuple[Any, ...]) -> None:
    if pd is None:
        raise SystemExit(f"pandas is required: {PANDAS_ERROR}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sheet_names = ["summary", "radon", "coupling", "cohesion", "architecture"]
        for sheet_name, frame in zip(sheet_names, frames, strict=False):
            frame.to_excel(writer, sheet_name=sheet_name, index=False)


def write_charts(output_dir: Path, frames: tuple[Any, ...]) -> None:
    if plt is None or pd is None:
        raise SystemExit(f"matplotlib and pandas are required: {MPL_ERROR}")
    summary_frame, radon_frame, coupling_frame, cohesion_frame, _ = frames
    output_dir.mkdir(parents=True, exist_ok=True)

    if not summary_frame.empty:
        summary_frame[["lines", "classes", "functions"]].sum().plot(kind="bar", title="Repository summary")
        plt.tight_layout()
        plt.savefig(output_dir / "summary.png", dpi=200)
        plt.close()

    if not radon_frame.empty:
        series = radon_frame["maintainability_index"].dropna()
        if not series.empty:
            series.plot(kind="hist", bins=15, title="Maintainability Index")
            plt.tight_layout()
            plt.savefig(output_dir / "mi_histogram.png", dpi=200)
            plt.close()

    if not coupling_frame.empty:
        coupling_frame.set_index("module")["cbo"].sort_values(ascending=False).head(20).plot(
            kind="bar", title="Top coupling"
        )
        plt.tight_layout()
        plt.savefig(output_dir / "coupling_top20.png", dpi=200)
        plt.close()

    if not cohesion_frame.empty:
        cohesion_frame["lcom"].dropna().plot(kind="hist", bins=15, title="LCOM approximation")
        plt.tight_layout()
        plt.savefig(output_dir / "cohesion_histogram.png", dpi=200)
        plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate evaluation reports")
    parser.add_argument("--input-dir", type=Path, default=None, help="Directory containing JSON outputs")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory where reports are written")
    parser.add_argument("--excel", type=Path, default=None, help="Optional Excel report path")
    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to analyze directly")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    args = parser.parse_args()

    if args.input_dir is not None:
        frames = build_frames(args.input_dir.resolve())
    elif args.repo is not None:
        if pd is None:
            raise SystemExit(f"pandas is required: {PANDAS_ERROR}")
        with resolve_repository_root(None, args.repo, args.branch) as root:
            frames = build_frames_from_repo(root)
    else:
        raise SystemExit("Provide either --input-dir or --repo")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name, frame in zip(["summary", "radon", "coupling", "cohesion", "architecture"], frames, strict=False):
        frame.to_csv(args.output_dir / f"{name}.csv", index=False)

    if args.excel is not None:
        write_excel(args.excel, frames)

    write_charts(args.output_dir / "charts", frames)


if __name__ == "__main__":
    main()
