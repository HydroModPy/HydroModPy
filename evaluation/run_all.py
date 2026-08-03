from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation._utils import resolve_repository_root, safe_mkdir
from evaluation.cohesion import compute_cohesion
from evaluation.coupling import compute_cbo
from evaluation.extract_architecture import collect_architecture, save_graph
from evaluation.generate_report import build_frames, build_frames_from_repo, write_excel, write_charts
from evaluation.radon_metrics import compute_radon_metrics
from evaluation.repository_summary import summarize_repository


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_for_root(root: Path, output_dir: Path, excel_path: Path | None) -> None:
    raw_dir = safe_mkdir(output_dir / "raw")
    report_dir = safe_mkdir(output_dir / "report")

    summary = summarize_repository(root)
    radon = compute_radon_metrics(root)
    coupling = compute_cbo(root)
    cohesion = compute_cohesion(root)
    architecture = collect_architecture(root)

    write_json(raw_dir / "summary.json", summary)
    write_json(raw_dir / "radon.json", radon)
    write_json(raw_dir / "coupling.json", coupling)
    write_json(raw_dir / "cohesion.json", cohesion)
    write_json(raw_dir / "architecture.json", {key: value for key, value in architecture.items() if key != "graph"})
    save_graph(architecture.get("graph"), raw_dir / "architecture_graph.png")

    if hasattr(__import__("pandas"), "DataFrame"):
        frames = build_frames(raw_dir)
        for name, frame in zip(["summary", "radon", "coupling", "cohesion", "architecture"], frames, strict=False):
            frame.to_csv(report_dir / f"{name}.csv", index=False)
        write_charts(report_dir / "charts", frames)
        if excel_path is not None:
            write_excel(excel_path, frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all evaluation scripts for a repository")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Local repository root")
    parser.add_argument("--repo", type=str, default=None, help="Remote repository URL or local path to clone")
    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout when cloning --repo")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory where results are written")
    parser.add_argument("--excel", type=Path, default=None, help="Optional Excel report path")
    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        excel_path = args.excel.expanduser().resolve() if args.excel is not None else output_dir / "evaluation.xlsx"
        run_for_root(root, output_dir, excel_path)


if __name__ == "__main__":
    main()
