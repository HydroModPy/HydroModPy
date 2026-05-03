"""Report long documentation pages that have no visual support.

This tool is intentionally lightweight and read-only. It is meant for manual
documentation passes, not as a hard CI gate while the documentation is still
being reorganized.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

VISUAL_RE = re.compile(r"^\s*\.\.\s+(figure|image|uml|graphviz)::", re.MULTILINE)
TOCTREE_RE = re.compile(r"^\s*\.\.\s+toctree::", re.MULTILINE)


@dataclass(frozen=True)
class PageVisualStats:
    """Visual coverage statistics for one RST page."""

    path: Path
    line_count: int
    visual_count: int
    has_toctree: bool


def _is_generated_or_out_of_scope(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    return (
        rel.startswith("api/generated/")
        or rel.startswith("capability_gallery/cases/")
        or rel.startswith("_templates/")
    )


def collect_page_stats(root: Path) -> list[PageVisualStats]:
    """Collect simple visual coverage statistics for manual RST pages."""

    stats: list[PageVisualStats] = []
    for path in sorted(root.rglob("*.rst")):
        if _is_generated_or_out_of_scope(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Auto-generated" in text[:500] or "auto-generated" in text[:500]:
            continue
        stats.append(
            PageVisualStats(
                path=path,
                line_count=len(text.splitlines()),
                visual_count=len(VISUAL_RE.findall(text)),
                has_toctree=TOCTREE_RE.search(text) is not None,
            )
        )
    return stats


def _markdown_path(path: Path) -> str:
    return path.as_posix()


def render_report(
    stats: list[PageVisualStats],
    *,
    root: Path,
    min_lines: int,
    max_rows: int,
) -> str:
    """Render the audit as Markdown."""

    long_content = [
        item
        for item in stats
        if item.line_count >= min_lines and (not item.has_toctree or item.line_count > 80)
    ]
    without_visuals = [item for item in long_content if item.visual_count == 0]
    sparse = [item for item in long_content if item.visual_count == 1]
    illustrated = [item for item in stats if item.visual_count > 0]

    without_visuals.sort(key=lambda item: (-item.line_count, item.path.as_posix()))
    sparse.sort(key=lambda item: (-item.line_count, item.path.as_posix()))

    lines: list[str] = []
    lines.append("# Documentation Visual Audit")
    lines.append("")
    lines.append(f"- Root: `{root.as_posix()}`")
    lines.append(f"- Manual RST pages scanned: {len(stats)}")
    lines.append(f"- Pages with at least one visual directive: {len(illustrated)}")
    lines.append(f"- Long content pages inspected: {len(long_content)}")
    lines.append(f"- Long content pages without visual directives: {len(without_visuals)}")
    lines.append("")
    lines.append("## Long Pages Without Visuals")
    lines.append("")
    lines.append("| Lines | Page |")
    lines.append("| ---: | --- |")
    for item in without_visuals[:max_rows]:
        rel = item.path.relative_to(root)
        lines.append(f"| {item.line_count} | `{_markdown_path(rel)}` |")
    lines.append("")
    lines.append("## Long Pages With One Visual")
    lines.append("")
    lines.append("| Lines | Page |")
    lines.append("| ---: | --- |")
    for item in sparse[:max_rows]:
        rel = item.path.relative_to(root)
        lines.append(f"| {item.line_count} | `{_markdown_path(rel)}` |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("docs/readthedocs/source"),
        help="Read the Docs source root.",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=120,
        help="Minimum page length to flag as long content.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=40,
        help="Maximum rows per report section.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    stats = collect_page_stats(root)
    print(
        render_report(
            stats,
            root=root,
            min_lines=args.min_lines,
            max_rows=args.max_rows,
        )
    )


if __name__ == "__main__":
    main()
