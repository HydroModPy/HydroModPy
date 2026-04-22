"""Typed public TOML contracts for the standalone mesh visualization package.

The public section name remains ``[mesh_distribution]`` for backward
compatibility, even though the code internally talks about "visualization".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..schema import (
    ALLOWED_COLOR_FIELDS,
    ALLOWED_TOPOGRAPHY_FIELDS,
    PlotConfig,
)
from .toml_docs import (
    MAIN_ALLOWED_KEYS,
    MAIN_LABEL,
    PLOT_ALLOWED_KEYS,
    PLOT_LABEL,
)
from .toml_validation import (
    ValidationError,
    coerce_bool,
    coerce_figure_size,
    coerce_non_negative_float,
    coerce_optional_path,
    coerce_optional_text,
    coerce_path,
    coerce_positive_int,
    coerce_required_text,
    forbid_unknown_keys,
    read_mapping_value,
    require_mapping,
)

PLOT_DEFAULTS = PlotConfig()


def normalize_color_field(value: object) -> str:
    """Validate one public `color_field` token."""

    text = coerce_required_text(value, label="color_field").lower()
    if text not in ALLOWED_COLOR_FIELDS:
        values = ", ".join(sorted(ALLOWED_COLOR_FIELDS))
        raise ValidationError(f"color_field must be one of: {values}.")
    return text


def normalize_topography_field(value: object) -> str:
    """Validate one public `topography_field` token."""

    text = coerce_required_text(value, label="topography_field").lower()
    if text not in ALLOWED_TOPOGRAPHY_FIELDS:
        values = ", ".join(sorted(ALLOWED_TOPOGRAPHY_FIELDS))
        raise ValidationError(f"topography_field must be one of: {values}.")
    return text


@dataclass(frozen=True)
class VisualizationPlotTomlSchema:
    """Validated schema of the ``[mesh_distribution.plot]`` block.

    This class represents the stable public TOML contract, not the runtime
    plotting object used internally during rendering.
    """

    color_field: str = PLOT_DEFAULTS.color_field
    color_map: str = PLOT_DEFAULTS.color_map
    figure_size: tuple[float, float] = PLOT_DEFAULTS.figure_size
    dpi: int = PLOT_DEFAULTS.dpi
    title: str | None = PLOT_DEFAULTS.title
    show_topography_panel: bool = PLOT_DEFAULTS.show_topography_panel
    topography_field: str = PLOT_DEFAULTS.topography_field
    topography_cmap: str = PLOT_DEFAULTS.topography_cmap
    topography_title: str | None = PLOT_DEFAULTS.topography_title
    show_mesh_edges: bool = PLOT_DEFAULTS.show_mesh_edges
    mesh_edge_color: str = PLOT_DEFAULTS.mesh_edge_color
    mesh_edge_linewidth: float = PLOT_DEFAULTS.mesh_edge_linewidth
    show_boundaries: bool = PLOT_DEFAULTS.show_boundaries
    show_geology_interfaces: bool = PLOT_DEFAULTS.show_geology_interfaces
    show_river_edges: bool = PLOT_DEFAULTS.show_river_edges
    annotate_cell_ids: bool = PLOT_DEFAULTS.annotate_cell_ids

    @classmethod
    def from_mapping(
        cls,
        raw_value: object | None,
    ) -> VisualizationPlotTomlSchema:
        """Validate the optional plot block from raw TOML content."""

        raw_plot = {} if raw_value is None else require_mapping(raw_value, label=PLOT_LABEL)
        forbid_unknown_keys(
            raw_plot,
            allowed_keys=PLOT_ALLOWED_KEYS,
            label=PLOT_LABEL,
        )
        defaults = PLOT_DEFAULTS
        return cls(
            color_field=read_mapping_value(
                raw_plot,
                "color_field",
                default=defaults.color_field,
                parser=normalize_color_field,
            ),
            color_map=read_mapping_value(
                raw_plot,
                "color_map",
                default=defaults.color_map,
                parser=coerce_required_text,
                label="color_map",
            ),
            figure_size=read_mapping_value(
                raw_plot,
                "figure_size",
                default=defaults.figure_size,
                parser=coerce_figure_size,
            ),
            dpi=read_mapping_value(
                raw_plot,
                "dpi",
                default=defaults.dpi,
                parser=coerce_positive_int,
                label="dpi",
            ),
            title=read_mapping_value(
                raw_plot,
                "title",
                default=defaults.title,
                parser=coerce_optional_text,
            ),
            show_topography_panel=read_mapping_value(
                raw_plot,
                "show_topography_panel",
                default=defaults.show_topography_panel,
                parser=coerce_bool,
                label="show_topography_panel",
            ),
            topography_field=read_mapping_value(
                raw_plot,
                "topography_field",
                default=defaults.topography_field,
                parser=normalize_topography_field,
            ),
            topography_cmap=read_mapping_value(
                raw_plot,
                "topography_cmap",
                default=defaults.topography_cmap,
                parser=coerce_required_text,
                label="topography_cmap",
            ),
            topography_title=read_mapping_value(
                raw_plot,
                "topography_title",
                default=defaults.topography_title,
                parser=coerce_optional_text,
            ),
            show_mesh_edges=read_mapping_value(
                raw_plot,
                "show_mesh_edges",
                default=defaults.show_mesh_edges,
                parser=coerce_bool,
                label="show_mesh_edges",
            ),
            mesh_edge_color=read_mapping_value(
                raw_plot,
                "mesh_edge_color",
                default=defaults.mesh_edge_color,
                parser=coerce_required_text,
                label="mesh_edge_color",
            ),
            mesh_edge_linewidth=read_mapping_value(
                raw_plot,
                "mesh_edge_linewidth",
                default=defaults.mesh_edge_linewidth,
                parser=coerce_non_negative_float,
                label="mesh_edge_linewidth",
            ),
            show_boundaries=read_mapping_value(
                raw_plot,
                "show_boundaries",
                default=defaults.show_boundaries,
                parser=coerce_bool,
                label="show_boundaries",
            ),
            show_geology_interfaces=read_mapping_value(
                raw_plot,
                "show_geology_interfaces",
                default=defaults.show_geology_interfaces,
                parser=coerce_bool,
                label="show_geology_interfaces",
            ),
            show_river_edges=read_mapping_value(
                raw_plot,
                "show_river_edges",
                default=defaults.show_river_edges,
                parser=coerce_bool,
                label="show_river_edges",
            ),
            annotate_cell_ids=read_mapping_value(
                raw_plot,
                "annotate_cell_ids",
                default=defaults.annotate_cell_ids,
                parser=coerce_bool,
                label="annotate_cell_ids",
            ),
        )

    def to_plot_config(self) -> PlotConfig:
        """Build the runtime plot config from the validated TOML contract."""

        return PlotConfig(**asdict(self))


@dataclass(frozen=True)
class MeshVisualizationTomlSchema:
    """Validated schema of the top-level ``[mesh_distribution]`` block.

    Use this class when documenting or validating the public file format.
    Convert it to ``VisualizationConfig`` before running the viewer.
    """

    bundle_dir: Path
    figure_output_path: Path | None = None
    summary_output_path: Path | None = None
    show_window: bool = False
    plot: VisualizationPlotTomlSchema = field(default_factory=VisualizationPlotTomlSchema)

    @classmethod
    def from_mapping(cls, raw_value: object) -> MeshVisualizationTomlSchema:
        """Validate the top-level public TOML block."""

        raw_main = require_mapping(raw_value, label=MAIN_LABEL)
        forbid_unknown_keys(
            raw_main,
            allowed_keys=MAIN_ALLOWED_KEYS,
            label=MAIN_LABEL,
        )
        return cls(
            bundle_dir=read_mapping_value(
                raw_main,
                "bundle_dir",
                default=None,
                parser=coerce_path,
                label="bundle_dir",
            ),
            figure_output_path=read_mapping_value(
                raw_main,
                "figure_output_path",
                default=None,
                parser=coerce_optional_path,
            ),
            summary_output_path=read_mapping_value(
                raw_main,
                "summary_output_path",
                default=None,
                parser=coerce_optional_path,
            ),
            show_window=read_mapping_value(
                raw_main,
                "show_window",
                default=False,
                parser=coerce_bool,
                label="show_window",
            ),
            plot=read_mapping_value(
                raw_main,
                "plot",
                default=None,
                parser=VisualizationPlotTomlSchema.from_mapping,
            ),
        )


__all__ = [
    "MeshVisualizationTomlSchema",
    "VisualizationPlotTomlSchema",
    "normalize_color_field",
    "normalize_topography_field",
]
