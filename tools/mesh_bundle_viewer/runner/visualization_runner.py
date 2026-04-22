"""High-level orchestration for the standalone mesh visualization workflow.

Execution flow:

1. load or validate configuration
2. load the bundle from disk
3. build the summary
4. render the figure
5. write requested outputs

For most Python callers, ``run_visualization_from_toml(...)`` is the best
entry point.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..display.figure import (
    build_visualization_figure,
)
from ..display.summary import (
    build_visualization_summary,
    build_visualization_summary_contract,
)
from ..loading.bundle_loader import (
    load_visualization_data,
    load_visualization_data_from_toml,
)
from ..loading.toml_loader import (
    load_toml_config,
)
from ..schema import (
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    MeshVisualizationData,
    PlotConfig,
    VisualizationConfig,
)
from ..visualization_summary import VisualizationSummary


def _write_json_file(path: Path, content: Mapping[str, Any]) -> None:
    """Write one stable, human-readable JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(content), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_requested_outputs(
    data: MeshVisualizationData,
    *,
    summary: VisualizationSummary,
    figure,
) -> None:
    """Write the figure and JSON summary requested by the config."""
    if data.config.figure_output_path is not None:
        data.config.figure_output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(data.config.figure_output_path)

    if data.config.summary_output_path is not None:
        _write_json_file(data.config.summary_output_path, summary.to_mapping())


def _finalize_figure(*, figure, show_window: bool) -> None:
    """Show or close the matplotlib figure depending on runtime config."""
    from matplotlib import pyplot as plt

    if show_window:
        plt.show()
    else:
        plt.close(figure)


def run_visualization(
    config: VisualizationConfig,
) -> dict[str, Any]:
    """Run the full visualization workflow from an already-built config.

    Use this entry point when a caller already owns a validated
    ``VisualizationConfig`` and wants the final summary mapping.
    """

    data = load_visualization_data(config)
    summary = build_visualization_summary_contract(data)
    figure = build_visualization_figure(
        data.mesh,
        config=data.config,
    )

    _write_requested_outputs(
        data,
        summary=summary,
        figure=figure,
    )
    _finalize_figure(
        figure=figure,
        show_window=data.config.show_window,
    )
    return summary.to_mapping()


def run_visualization_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
    forced_summary_output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full visualization workflow directly from one TOML file.

    This is the recommended high-level Python API for simple integrations.
    """

    config = load_toml_config(toml_path, section=section)

    if forced_summary_output_path is not None:
        config = replace(
            config,
            summary_output_path=Path(forced_summary_output_path).resolve(),
        )

    return run_visualization(config)


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_TOML_SECTION",
    "MeshVisualizationData",
    "PlotConfig",
    "VisualizationConfig",
    "VisualizationSummary",
    "build_visualization_summary",
    "build_visualization_summary_contract",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
    "run_visualization",
    "run_visualization_from_toml",
]
