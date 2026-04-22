"""Diagnostic plotting helpers for MODFLOW 6 runtime support exports."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

import numpy as np

from hydromodpy.core.tools import filesystem
from hydromodpy.solver.modflow_common.options import ModflowPostprocessOptions


class RuntimeSupportLike(Protocol):
	"""Minimal runtime-support contract used by overview plotting helpers."""

	edge_ids: np.ndarray
	node_x_m: np.ndarray
	node_y_m: np.ndarray
	edge_node_a_index: np.ndarray
	edge_node_b_index: np.ndarray
	cell_node_indices: tuple[tuple[int, ...], ...]
	cell_centroid_x_m: np.ndarray
	cell_centroid_y_m: np.ndarray
	edge_midpoint_x_m: np.ndarray
	edge_midpoint_y_m: np.ndarray
	boundary_labels_by_edge_id: Mapping[int, object]

	def river_edge_indices(self) -> np.ndarray: ...

	def edge_indices_for_label(self, label: str) -> np.ndarray: ...


class RuntimeSupportOverviewModel(Protocol):
	"""Minimal MODFLOW-6 contract consumed by runtime support overview exports."""

	flow: object | None
	save_file: str
	runtime_mesh_support: RuntimeSupportLike | None
	grid_ctx: object | None

	def _boundary_conditions_mapping(self) -> Mapping[str, object]: ...

	def _is_bc_active(self, bc_id: str) -> bool: ...

	def _boundary_attr(self, boundary: object, name: str, default=None): ...

	def _boundary_support_cell_ids(self, *, boundary: object, bc_id: str) -> list[int]: ...

	def _resolve_stream_boundary_series(self) -> np.ndarray | None: ...

	def _stream_chd_support_mask(self, stream_series: np.ndarray | None) -> np.ndarray: ...

	def _resolve_ocean_boundary_series(self) -> np.ndarray | None: ...

	def _ocean_chd_support_mask(self, ocean_series: np.ndarray | None) -> np.ndarray: ...

	def _resolve_well_disv_cell(
		self,
		*,
		well_id: str,
		well_cfg: object,
		grid: object | None,
	) -> tuple[int, int]: ...


def support_edge_segments(support: RuntimeSupportLike, edge_indices: np.ndarray) -> list[np.ndarray]:
	"""Return XY segments for one sequence of runtime support edge indices."""
	indices = np.asarray(edge_indices, dtype=int).reshape(-1)
	if indices.size == 0:
		return []
	node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
	node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
	edge_node_a = np.asarray(getattr(support, "edge_node_a_index", ()), dtype=int).reshape(-1)
	edge_node_b = np.asarray(getattr(support, "edge_node_b_index", ()), dtype=int).reshape(-1)
	segments: list[np.ndarray] = []
	for edge_index in indices.tolist():
		if edge_index < 0 or edge_index >= edge_node_a.size or edge_index >= edge_node_b.size:
			continue
		node_a = int(edge_node_a[edge_index])
		node_b = int(edge_node_b[edge_index])
		segments.append(
			np.asarray(
				[
					[float(node_x_m[node_a]), float(node_y_m[node_a])],
					[float(node_x_m[node_b]), float(node_y_m[node_b])],
				],
				dtype=float,
			)
		)
	return segments


def support_cell_polygons(support: RuntimeSupportLike, cell_ids: np.ndarray) -> list[np.ndarray]:
	"""Return XY polygons for one sequence of runtime support cell ids."""
	indices = np.asarray(cell_ids, dtype=int).reshape(-1)
	if indices.size == 0:
		return []
	node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
	node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
	cell_node_indices = tuple(getattr(support, "cell_node_indices", ()) or ())
	polygons: list[np.ndarray] = []
	for cell_id in np.unique(indices).tolist():
		if cell_id < 0 or cell_id >= len(cell_node_indices):
			continue
		node_indices = np.asarray(cell_node_indices[int(cell_id)], dtype=int).reshape(-1)
		if node_indices.size < 3:
			continue
		polygons.append(
			np.column_stack([node_x_m[node_indices], node_y_m[node_indices]]).astype(
				float,
				copy=False,
			)
		)
	return polygons


def build_support_overlay_specs(model: RuntimeSupportOverviewModel) -> list[tuple[str, np.ndarray, str]]:
	"""Return active runtime support selections to visualize on one overview figure."""
	if model.flow is None:
		return []

	overlays: list[tuple[str, np.ndarray, str]] = []
	color_by_bc = {
		"west_side": "#d62728",
		"east_side": "#1f77b4",
		"north_side": "#ff7f0e",
		"south_side": "#9467bd",
		"stream": "#17becf",
		"ocean": "#2ca02c",
	}
	boundary_conditions = model._boundary_conditions_mapping()
	for bc_id in ("west_side", "east_side", "north_side", "south_side"):
		if not model._is_bc_active(bc_id):
			continue
		boundary = boundary_conditions.get(bc_id)
		if boundary is None:
			continue
		cell_ids = np.asarray(
			model._boundary_support_cell_ids(boundary=boundary, bc_id=bc_id),
			dtype=int,
		).reshape(-1)
		if cell_ids.size == 0:
			continue
		support_label = model._boundary_attr(boundary, "support_label", None)
		label = str(bc_id)
		if support_label is not None:
			label = f"{bc_id} [{str(support_label)}]"
		overlays.append((label, cell_ids, color_by_bc[bc_id]))

	if model._is_bc_active("stream"):
		stream_series = model._resolve_stream_boundary_series()
		stream_mask = model._stream_chd_support_mask(stream_series)
		stream_cell_ids = np.flatnonzero(np.asarray(stream_mask, dtype=bool)).astype(int, copy=False)
		if stream_cell_ids.size > 0:
			stream_boundary = boundary_conditions.get("stream")
			support_label = None if stream_boundary is None else model._boundary_attr(
				stream_boundary,
				"support_label",
				None,
			)
			label = "stream"
			if support_label is not None:
				label = f"stream [{str(support_label)}]"
			overlays.append((label, stream_cell_ids, color_by_bc["stream"]))

	if model._is_bc_active("ocean"):
		ocean_series = model._resolve_ocean_boundary_series()
		ocean_mask = model._ocean_chd_support_mask(ocean_series)
		ocean_cell_ids = np.flatnonzero(np.asarray(ocean_mask, dtype=bool)).astype(int, copy=False)
		if ocean_cell_ids.size > 0:
			overlays.append(("ocean", ocean_cell_ids, color_by_bc["ocean"]))

	return overlays


def build_well_overlay_specs(model: RuntimeSupportOverviewModel) -> list[dict[str, object]]:
	"""Return resolved well locations suitable for diagnostic plotting."""
	if model.flow is None:
		return []
	active = getattr(model.flow, "active_sinks_sources", [])
	if "wells" not in active:
		return []

	sinks_sources = getattr(model.flow, "sinks_sources", {})
	if not isinstance(sinks_sources, Mapping):
		return []
	wells = sinks_sources.get("wells", {})
	if not isinstance(wells, Mapping):
		return []

	support = getattr(model, "runtime_mesh_support", None)
	grid = None if model.grid_ctx is None else model.grid_ctx.grid
	items: list[dict[str, object]] = []
	for well_id, well_cfg in wells.items():
		try:
			_, cell_id = model._resolve_well_disv_cell(
				well_id=str(well_id),
				well_cfg=well_cfg,
				grid=grid,
			)
		except Exception:
			continue

		if support is not None and 0 <= int(cell_id) < int(getattr(support, "n_cells", 0)):
			x_m = float(np.asarray(support.cell_centroid_x_m, dtype=float).reshape(-1)[int(cell_id)])
			y_m = float(np.asarray(support.cell_centroid_y_m, dtype=float).reshape(-1)[int(cell_id)])
		else:
			continue
		items.append(
			{
				"id": str(well_id),
				"cell_id": int(cell_id),
				"x_m": x_m,
				"y_m": y_m,
			}
		)
	return items


def export_runtime_support_overview(
	model: RuntimeSupportOverviewModel,
	*,
	options: ModflowPostprocessOptions,
) -> None:
	"""Write one diagnostic figure showing runtime gmsh supports used by the solver."""
	if not getattr(options, "native_mesh_png", False):
		return
	support = getattr(model, "runtime_mesh_support", None)
	if support is None:
		return

	import matplotlib

	matplotlib.use("Agg", force=True)
	import matplotlib.pyplot as plt
	from matplotlib.collections import LineCollection, PolyCollection
	from matplotlib.lines import Line2D
	from matplotlib.patches import Patch

	figure_dir = os.path.join(model.save_file, "_figures", "native_mesh")
	filesystem.create_folder(figure_dir)

	all_edge_indices = np.arange(np.asarray(getattr(support, "edge_ids", ()), dtype=int).size, dtype=int)
	all_segments = support_edge_segments(support, all_edge_indices)
	if not all_segments:
		return

	node_x_m = np.asarray(getattr(support, "node_x_m", ()), dtype=float).reshape(-1)
	node_y_m = np.asarray(getattr(support, "node_y_m", ()), dtype=float).reshape(-1)
	fig, axs = plt.subplots(1, 2, figsize=(14.8, 6.4), dpi=220)
	ax_active, ax_labels = axs

	for ax in (ax_active, ax_labels):
		ax.add_collection(LineCollection(all_segments, colors="0.80", linewidths=0.8, zorder=1))
		ax.set_aspect("equal")
		ax.set_xlim(float(np.min(node_x_m)), float(np.max(node_x_m)))
		ax.set_ylim(float(np.min(node_y_m)), float(np.max(node_y_m)))
		ax.set_xlabel("x (m)", fontsize=9)
		ax.set_ylabel("y (m)", fontsize=9)
		ax.ticklabel_format(style="plain", axis="both", useOffset=False)
		ax.tick_params(axis="both", labelsize=8, length=3.0, pad=2.0)

	active_handles: list[object] = []
	for label, cell_ids, color in build_support_overlay_specs(model):
		polygons = support_cell_polygons(support, cell_ids)
		if not polygons:
			continue
		ax_active.add_collection(
			PolyCollection(
				polygons,
				facecolors=color,
				edgecolors=color,
				linewidths=1.4,
				alpha=0.22,
				zorder=2,
			)
		)
		active_handles.append(Patch(facecolor=color, edgecolor=color, alpha=0.22, label=label))

	river_indices = np.asarray(support.river_edge_indices(), dtype=int).reshape(-1)
	river_segments = support_edge_segments(support, river_indices)
	if river_segments:
		river_collection = LineCollection(
			river_segments,
			colors="#17becf",
			linewidths=2.0,
			alpha=0.95,
			zorder=3,
		)
		ax_active.add_collection(river_collection)
		ax_labels.add_collection(
			LineCollection(
				river_segments,
				colors="#17becf",
				linewidths=2.0,
				alpha=0.95,
				zorder=3,
			)
		)
		active_handles.append(Line2D([0], [0], color="#17becf", lw=2.0, label="river edges"))

	well_items = build_well_overlay_specs(model)
	if well_items:
		ax_active.scatter(
			[float(item["x_m"]) for item in well_items],
			[float(item["y_m"]) for item in well_items],
			marker="x",
			s=55.0,
			linewidths=1.5,
			color="black",
			zorder=4,
		)
		for item in well_items:
			ax_active.text(
				float(item["x_m"]),
				float(item["y_m"]),
				str(item["id"]),
				fontsize=7.5,
				color="black",
				ha="left",
				va="bottom",
				zorder=5,
			)
		active_handles.append(
			Line2D([0], [0], marker="x", color="black", linestyle="None", label="wells")
		)

	label_handles: list[object] = []
	label_values = sorted(
		{
			str(value)
			for value in getattr(support, "boundary_labels_by_edge_id", {}).values()
			if str(value).strip() != ""
		}
	)
	palette = (
		"#d62728",
		"#1f77b4",
		"#ff7f0e",
		"#9467bd",
		"#8c564b",
		"#e377c2",
		"#7f7f7f",
		"#bcbd22",
	)
	for index, label in enumerate(label_values):
		edge_indices = np.asarray(support.edge_indices_for_label(label), dtype=int).reshape(-1)
		segments = support_edge_segments(support, edge_indices)
		if not segments:
			continue
		color = palette[index % len(palette)]
		ax_labels.add_collection(
			LineCollection(
				segments,
				colors=color,
				linewidths=2.4,
				alpha=0.95,
				zorder=2,
			)
		)
		x_mid = float(np.mean(np.asarray(support.edge_midpoint_x_m, dtype=float).reshape(-1)[edge_indices]))
		y_mid = float(np.mean(np.asarray(support.edge_midpoint_y_m, dtype=float).reshape(-1)[edge_indices]))
		ax_labels.text(
			x_mid,
			y_mid,
			label,
			fontsize=7.5,
			color=color,
			ha="center",
			va="center",
			bbox={"facecolor": "white", "edgecolor": color, "alpha": 0.75, "pad": 1.5},
			zorder=4,
		)
		label_handles.append(Line2D([0], [0], color=color, lw=2.4, label=label))

	ax_active.set_title("Active supports", fontsize=10.5, loc="left", pad=5.0)
	ax_labels.set_title("Support labels", fontsize=10.5, loc="left", pad=5.0)
	if active_handles:
		ax_active.legend(
			handles=active_handles,
			loc="upper center",
			bbox_to_anchor=(0.5, -0.12),
			ncol=min(3, len(active_handles)),
			fontsize=7.5,
			frameon=True,
			framealpha=0.92,
		)
	if label_handles:
		ax_labels.legend(
			handles=label_handles,
			loc="upper center",
			bbox_to_anchor=(0.5, -0.12),
			ncol=min(3, len(label_handles)),
			fontsize=7.5,
			frameon=True,
			framealpha=0.92,
		)
	else:
		ax_labels.text(
			0.5,
			0.5,
			"No labeled runtime supports",
			transform=ax_labels.transAxes,
			ha="center",
			va="center",
			fontsize=9,
			color="0.35",
		)

	fig.suptitle("Runtime support overview", fontsize=11.5, y=0.96)
	fig.subplots_adjust(left=0.055, right=0.985, bottom=0.2, top=0.88, wspace=0.12)
	fig.savefig(
		os.path.join(figure_dir, "flow_support_overview.png"),
		bbox_inches="tight",
	)
	plt.close(fig)


__all__ = [
	"RuntimeSupportLike",
	"RuntimeSupportOverviewModel",
	"build_support_overlay_specs",
	"build_well_overlay_specs",
	"export_runtime_support_overview",
	"support_cell_polygons",
	"support_edge_segments",
]
