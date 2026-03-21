"""Orchestration complete de la distribution de maillage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from mesh.display.figure import (
    build_visualization_figure,
)
from mesh.display.summary import (
    build_visualization_summary,
)
from mesh.loading.bundle_loader import (
    load_visualization_data,
    load_visualization_data_from_toml,
)
from mesh.loading.toml_loader import (
    load_toml_config,
)
from mesh.schema import (
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    MeshVisualizationData,
    PlotConfig,
    VisualizationConfig,
)


def _write_json_file(path: Path, content: Mapping[str, Any]) -> None:
    """Ecrit un JSON lisible et stable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(content), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_requested_outputs(
    data: MeshVisualizationData,
    *,
    summary: Mapping[str, Any],
    figure,
) -> None:
    """Ecrit les sorties demandees par la configuration."""
    if data.config.figure_output_path is not None:
        data.config.figure_output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(data.config.figure_output_path)

    if data.config.summary_output_path is not None:
        _write_json_file(data.config.summary_output_path, summary)


def _finalize_figure(*, figure, show_window: bool) -> None:
    """Affiche ou ferme proprement la figure matplotlib."""
    from matplotlib import pyplot as plt

    if show_window:
        plt.show()
    else:
        plt.close(figure)


def run_visualization(
    config: VisualizationConfig,
) -> dict[str, Any]:
    """Execute la lecture, le rendu et l'ecriture des sorties."""

    data = load_visualization_data(config)
    summary = build_visualization_summary(data)
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
    return summary


def run_visualization_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
    forced_summary_output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Point d'entree de haut niveau pour lancer l'outil depuis un TOML."""

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
    "build_visualization_summary",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
    "run_visualization",
    "run_visualization_from_toml",
]
