"""Reusable compact HTML synthesis for network-distance comparisons."""

from __future__ import annotations

import csv
import html
import json
import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class InfoCard:
    title: str
    body_html: str


@dataclass(frozen=True)
class GroupSection:
    group_id: str
    title: str
    intro: str


@dataclass(frozen=True)
class SimulationMeta:
    simulation_id: str
    label: str
    group: str
    purpose: str = ""
    mesh_summary: str = ""
    short_label: str = ""


@dataclass(frozen=True)
class CompactNetworkSynthesisConfig:
    comparison_root: Path
    page_path: Path
    title: str
    intro: str
    simulations: Sequence[SimulationMeta] = ()
    group_sections: Sequence[GroupSection] = ()
    contract_cards: Sequence[InfoCard] = ()
    interpretation_cards: Sequence[InfoCard] = ()
    base_config: Path | None = None
    comparison_id: str | None = None
    context_watershed_path: Path | None = None


@dataclass
class SimulationRecord:
    meta: SimulationMeta
    simulation_label: str = ""
    solver: str = ""
    mesh_mode: str = ""
    mesh_label: str = ""
    run_info: dict[str, str] = field(default_factory=dict)
    closure: dict[str, str] = field(default_factory=dict)
    release_distance: dict[str, str] | None = None
    accumulation_distance: dict[str, str] | None = None
    release_accumulation_distance: dict[str, str] | None = None
    vector_network: dict[str, str] | None = None


def _safe(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "")
        if value:
            return value
    return ""


def _fmt_m(value: object) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fmt_ratio(value: object) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _parse_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _row_value(row: dict[str, str] | None, name: str) -> str:
    if row is None:
        return ""
    return row.get(name, "")


def resolve_recorded_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if os.name == "nt" and text.startswith("/mnt/") and len(text) > 7 and text[5].isalpha():
        return Path(f"{text[5].upper()}:/{text[7:]}").resolve()
    if os.name != "nt" and len(text) > 2 and text[1] == ":" and text[0].isalpha():
        drive = text[0].lower()
        tail = text[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{tail}").resolve()
    return Path(text).expanduser().resolve()


class CompactNetworkSynthesisBuilder:
    """Build the compact network synthesis page for one comparison root."""

    def __init__(self, config: CompactNetworkSynthesisConfig):
        self.config = config
        self.comparison_root = Path(config.comparison_root)
        self.page_path = Path(config.page_path)
        self.figure_root = self.page_path.parent / "field_figures"
        self.context_figure_path = self.page_path.parent / "topographic_context.png"
        self.recharge_figure_path = self.page_path.parent / "recharge_forcing.png"
        self.metric_synthesis_figure_path = self.page_path.parent / "distance_ratio_synthesis.png"
        self.meta_by_id = {item.simulation_id: item for item in config.simulations}
        self._context_watershed_cache = None

    def read_csv(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def read_json(self, path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}

    def read_toml(self, path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        return data if isinstance(data, dict) else {}

    def relative_path(self, path: Path) -> str:
        return os.path.relpath(path, self.page_path.parent).replace(os.sep, "/")

    def _record_for(
        self, records: dict[str, SimulationRecord], simulation_id: str
    ) -> SimulationRecord:
        meta = self.meta_by_id.get(
            simulation_id,
            SimulationMeta(simulation_id, simulation_id, "autres"),
        )
        return records.setdefault(simulation_id, SimulationRecord(meta=meta))

    def records_by_simulation(self) -> list[SimulationRecord]:
        records: dict[str, SimulationRecord] = {}
        manifest = self.read_json(self.comparison_root / "comparison_manifest.json")
        manifest_simulations = manifest.get("simulations", [])
        if isinstance(manifest_simulations, list):
            for item in manifest_simulations:
                if not isinstance(item, dict):
                    continue
                simulation_id = str(item.get("id") or item.get("simulation_id") or "")
                if not simulation_id:
                    continue
                record = self._record_for(records, simulation_id)
                record.run_info = {
                    str(key): "" if value is None else str(value)
                    for key, value in item.items()
                }
                record.simulation_label = record.simulation_label or _first(
                    record.run_info,
                    "label",
                    "simulation_label",
                )
                record.solver = record.solver or _first(record.run_info, "solver")
                record.mesh_mode = record.mesh_mode or _first(record.run_info, "mesh_mode")
                record.mesh_label = record.mesh_label or _first(record.run_info, "mesh_label")

        for filename, attr in (
            ("release_flux_network_distance_metrics.csv", "release_distance"),
            ("simulated_active_network_distance_metrics.csv", "accumulation_distance"),
            (
                "release_accumulation_network_distance_metrics.csv",
                "release_accumulation_distance",
            ),
            ("hydrographic_network_metrics.csv", "vector_network"),
        ):
            for row in self.read_csv(self.comparison_root / filename):
                simulation_id = _first(row, "simulation_id")
                if not simulation_id:
                    continue
                record = self._record_for(records, simulation_id)
                record.simulation_label = record.simulation_label or _first(
                    row, "simulation_label"
                )
                record.solver = record.solver or _first(row, "solver")
                record.mesh_mode = record.mesh_mode or _first(row, "mesh_mode")
                record.mesh_label = record.mesh_label or _first(row, "mesh_label")
                setattr(record, attr, row)

        for row in self.read_csv(self.comparison_root / "numerical_closure_summary.csv"):
            simulation_id = _first(row, "simulation_id")
            if not simulation_id:
                continue
            record = self._record_for(records, simulation_id)
            record.simulation_label = record.simulation_label or _first(
                row, "simulation_label"
            )
            record.solver = record.solver or _first(row, "solver")
            record.closure = row

        if self.config.simulations:
            ordered = [
                self._record_for(records, meta.simulation_id)
                for meta in self.config.simulations
            ]
            seen = {record.meta.simulation_id for record in ordered}
            ordered.extend(record for key, record in sorted(records.items()) if key not in seen)
            return ordered
        return [record for _, record in sorted(records.items())]

    def all_bidirectional_distances(self, records: Iterable[SimulationRecord]) -> list[float]:
        values: list[float] = []
        for record in records:
            for row in (
                record.release_distance,
                record.accumulation_distance,
                record.release_accumulation_distance,
            ):
                if not row:
                    continue
                parsed = _parse_float(row.get("bidirectional_distance_mean_m"))
                if parsed is not None:
                    values.append(parsed)
        return values

    @staticmethod
    def routed_distance(record: SimulationRecord) -> dict[str, str] | None:
        return record.release_accumulation_distance or record.accumulation_distance

    @staticmethod
    def solver_summary(record: SimulationRecord) -> str:
        if record.solver == "modflow6":
            return "MODFLOW 6"
        if record.solver == "boussinesq":
            return "Boussinesq"
        return record.solver or "solveur non renseigne"

    def mesh_summary(self, record: SimulationRecord) -> str:
        title = (
            record.meta.mesh_summary
            or record.mesh_label
            or record.mesh_mode
            or "maillage non renseigne"
        )
        cell_count = (
            _row_value(record.release_distance, "catchment_cell_count")
            or _row_value(record.release_accumulation_distance, "catchment_cell_count")
            or _row_value(record.accumulation_distance, "catchment_cell_count")
        )
        detail = (
            f"{_safe(_fmt_m(cell_count))} cellules de calcul"
            if cell_count
            else "nombre de cellules non disponible"
        )
        return f"{_safe(title.replace('_', ' '))}; {detail}"

    def configuration_cell(self, record: SimulationRecord) -> str:
        return (
            '<td class="config-cell">'
            f"<strong>{_safe(record.meta.label)}</strong>"
            f'<span class="sub">{_safe(self.solver_summary(record))}; '
            f"{self.mesh_summary(record)}</span>"
            "</td>"
        )

    @staticmethod
    def _source_row(record: SimulationRecord) -> dict[str, str]:
        if record.run_info.get("sim_id") and record.run_info.get("run_folder"):
            return record.run_info
        return (
            record.release_distance
            or record.release_accumulation_distance
            or record.accumulation_distance
            or record.run_info
            or {}
        )

    @staticmethod
    def metric_bar(row: dict[str, str] | None, max_distance: float) -> str:
        if row is None:
            return ""
        value = row.get("bidirectional_distance_mean_m", "")
        try:
            width = max(4.0, min(100.0, 100.0 * float(value) / max_distance))
        except (TypeError, ValueError, ZeroDivisionError):
            width = 0.0
        return f'<div class="bar" style="width:{width:.1f}%"></div>'

    def metric_grid(self, row: dict[str, str], max_distance: float) -> str:
        return f"""
<div class="metric-box">
  {self.metric_bar(row, max_distance)}
  <div class="metric-grid">
    <div><span>calc &rarr; obs moy.</span><strong>{_safe(_fmt_m(row.get("sim_to_network_distance_mean_m", "")))} m</strong></div>
    <div><span>obs &rarr; calc moy.</span><strong>{_safe(_fmt_m(row.get("network_to_sim_distance_mean_m", "")))} m</strong></div>
    <div><span>ratio</span><strong>{_safe(_fmt_ratio(row.get("planar_distance_ratio", "")))}</strong></div>
    <div><span>moyenne sym.</span><strong>{_safe(_fmt_m(row.get("bidirectional_distance_mean_m", "")))} m</strong></div>
  </div>
</div>
"""

    def figure_path(self, record: SimulationRecord, variable: str) -> Path:
        return self.figure_root / record.meta.simulation_id / f"{variable}_log_intensity.png"

    def figure_preview(self, record: SimulationRecord, variable: str, label: str) -> str:
        path = self.figure_path(record, variable)
        if not path.exists():
            return '<div class="figure-missing">figure non disponible</div>'
        rel = self.relative_path(path)
        title = f"{record.meta.label} - {label}"
        return f"""
<figure class="method-figure">
  <a href="{_safe(rel)}" class="figure-link" data-lightbox-src="{_safe(rel)}" data-lightbox-title="{_safe(title)}" title="Cliquer pour agrandir">
    <img src="{_safe(rel)}" alt="{_safe(title)}" loading="lazy">
  </a>
  <figcaption>{_safe(label)}</figcaption>
</figure>
"""

    def method_cell(
        self,
        record: SimulationRecord,
        *,
        row: dict[str, str] | None,
        variable: str,
        label: str,
        description: str,
        missing: str,
        max_distance: float,
    ) -> str:
        if row is None:
            return f"""
<td class="method-cell">
  <div class="method-title">{_safe(label)}</div>
  <p>{_safe(description)}</p>
  <div class="figure-missing">{_safe(missing)}</div>
</td>
"""
        return f"""
<td class="method-cell">
  <div class="method-title">{_safe(label)}</div>
  <p>{_safe(description)}</p>
  {self.figure_preview(record, variable, label)}
  {self.metric_grid(row, max_distance)}
</td>
"""

    def comparison_table(self, records: list[SimulationRecord], *, group: str) -> str:
        max_distance = max(self.all_bidirectional_distances(records) or [1.0])
        rows = []
        for record in records:
            if record.meta.group != group:
                continue
            rows.append(
                "<tr>"
                f"{self.configuration_cell(record)}"
                + self.method_cell(
                    record,
                    row=record.release_distance,
                    variable="release_flux",
                    label="Emergences calculees avant routage",
                    description=(
                        "Mailles ou le modele calcule une sortie d'eau vers la surface: "
                        "drain + surface excess, avant accumulation aval."
                    ),
                    missing="metrique non disponible",
                    max_distance=max_distance,
                )
                + self.method_cell(
                    record,
                    row=self.routed_distance(record),
                    variable="release_accumulation_flux",
                    label="Emergences accumulees vers l'aval",
                    description=(
                        "Les emergences sont routees vers l'aval sur le support numerique, "
                        "puis comparees au reseau observe."
                    ),
                    missing="non calcule pour cette configuration",
                    max_distance=max_distance,
                )
                + "</tr>"
            )
        if not rows:
            rows.append('<tr><td colspan="3" class="missing">Aucune simulation dans ce groupe.</td></tr>')
        return f"""
<table class="comparison-table">
  <thead>
    <tr>
      <th>configuration calculee</th>
      <th>emergences calculees avant routage</th>
      <th>emergences accumulees vers l'aval</th>
    </tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""

    @staticmethod
    def _field_stack(run, variable: str):
        import numpy as np

        n_timesteps = int(run.n_timesteps or 1)
        return np.stack(
            [
                np.asarray(run.field(variable, timestep=t), dtype="float64").reshape(-1)
                for t in range(n_timesteps)
            ]
        )

    def _mean_positive_flux(self, run, variable: str):
        import numpy as np

        stack = self._field_stack(run, variable)
        positive = np.where(np.isfinite(stack) & (stack > 0.0), stack, np.nan)
        with np.errstate(invalid="ignore"):
            return np.nanmean(positive, axis=0)

    @staticmethod
    def _log10_positive(values):
        import numpy as np

        values = np.asarray(values, dtype="float64").reshape(-1)
        out = np.full(values.shape, np.nan, dtype="float64")
        mask = np.isfinite(values) & (values > 0.0)
        out[mask] = np.log10(values[mask])
        return out

    def _fallback_reference_network(self):
        import geopandas as gpd
        from shapely.geometry import LineString

        cached = getattr(self, "_fallback_reference_network_cache", None)
        if cached is not None:
            return cached

        def bundle_candidates() -> list[Path]:
            manifest = self.read_json(self.comparison_root / "comparison_manifest.json")
            candidates: list[Path] = []
            simulations = manifest.get("simulations", [])
            if isinstance(simulations, list):
                for item in simulations:
                    if not isinstance(item, dict):
                        continue
                    config_path_raw = str(item.get("config_path") or "")
                    if config_path_raw:
                        config_path = resolve_recorded_path(config_path_raw)
                        cfg = self.read_toml(config_path)
                        mesh_input = cfg.get("mesh_input", {})
                        if isinstance(mesh_input, dict):
                            raw_bundle = str(mesh_input.get("bundle_dir") or "")
                            if raw_bundle:
                                candidates.append(resolve_recorded_path(raw_bundle))
                    run_folder_raw = str(item.get("run_folder") or "")
                    if run_folder_raw:
                        run_folder = resolve_recorded_path(run_folder_raw)
                        candidates.append(run_folder / "mesh" / "mesh_catchment_bundle")
            return candidates

        for bundle_dir in bundle_candidates():
            mesh_path = bundle_dir / "mesh_2d.msh"
            metadata = self.read_json(bundle_dir / "metadata.json")
            crs = str(metadata.get("crs") or "EPSG:2154")
            files = metadata.get("files")
            if isinstance(files, dict) and files.get("mesh"):
                mesh_path = bundle_dir / str(files["mesh"])
            if not mesh_path.exists():
                continue
            lines = self._gmsh_physical_lines(mesh_path, physical_name="river::trace")
            if not lines:
                continue
            gdf = gpd.GeoDataFrame(
                {"role": ["reference"] * len(lines)},
                geometry=[LineString(line) for line in lines],
                crs=crs,
            )
            self._fallback_reference_network_cache = gdf
            return gdf

        self._fallback_reference_network_cache = gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")
        return self._fallback_reference_network_cache

    @staticmethod
    def _gmsh_physical_lines(
        mesh_path: Path,
        *,
        physical_name: str,
    ) -> list[list[tuple[float, float]]]:
        import re

        lines = mesh_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        physical_tag: int | None = None
        nodes: dict[int, tuple[float, float]] = {}
        out: list[list[tuple[float, float]]] = []

        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if line == "$PhysicalNames":
                count = int(lines[index + 1].strip())
                for raw in lines[index + 2 : index + 2 + count]:
                    match = re.match(r'(\d+)\s+(\d+)\s+"(.*)"', raw.strip())
                    if match and int(match.group(1)) == 1 and match.group(3) == physical_name:
                        physical_tag = int(match.group(2))
                index += count + 2
                continue
            if line == "$Nodes":
                count = int(lines[index + 1].strip())
                for raw in lines[index + 2 : index + 2 + count]:
                    parts = raw.split()
                    if len(parts) >= 4:
                        nodes[int(parts[0])] = (float(parts[1]), float(parts[2]))
                index += count + 2
                continue
            if line == "$Elements":
                count = int(lines[index + 1].strip())
                if physical_tag is None:
                    return []
                for raw in lines[index + 2 : index + 2 + count]:
                    parts = raw.split()
                    if len(parts) < 6:
                        continue
                    element_type = int(parts[1])
                    if element_type not in (1, 8):
                        continue
                    tag_count = int(parts[2])
                    tags = [int(value) for value in parts[3 : 3 + tag_count]]
                    if not tags or tags[0] != physical_tag:
                        continue
                    node_ids = [int(value) for value in parts[3 + tag_count :]]
                    coords = [nodes[node_id] for node_id in node_ids if node_id in nodes]
                    if len(coords) >= 2:
                        out.append(coords)
                index += count + 2
                continue
            index += 1
        return out

    @staticmethod
    def _distance_metrics_with_external_network(
        run,
        network_gdf,
        *,
        variable: str,
        threshold: float = 0.0,
        mode=None,
        persistence_threshold: float = 0.5,
        timestep: int | None = None,
        network_buffer_m: float = 0.0,
    ) -> dict[str, float | int | str | None]:
        import numpy as np

        from hydromodpy.results.views import (
            _cell_field_active_state,
            _distance_stats,
            _finite_mean,
            _intersecting_cell_mask,
            _mesh_face_polygons,
            _nearest_distances,
            _network_geometries,
        )

        resolved_mode, values, valid, active = _cell_field_active_state(
            run,
            variable=variable,
            threshold=threshold,
            mode=mode,
            persistence_threshold=persistence_threshold,
            timestep=timestep,
        )
        polygons = _mesh_face_polygons(run)
        if polygons.size != values.size:
            raise ValueError(
                "Mesh polygon count does not match cell-field size: "
                f"mesh={polygons.size}, field={values.size}."
            )
        network_geometries = _network_geometries(
            network_gdf,
            buffer_m=float(network_buffer_m),
        )
        network_cells = _intersecting_cell_mask(polygons, network_geometries) & valid
        active_polygons = [
            polygon for polygon, is_active in zip(polygons, active, strict=True) if is_active
        ]
        active_polygons = [polygon for polygon in active_polygons if polygon is not None]
        active_centroids = [polygon.centroid for polygon in active_polygons]
        network_centroids = [
            polygon.centroid
            for polygon, is_network in zip(polygons, network_cells, strict=True)
            if is_network and polygon is not None
        ]
        sim_to_network = _distance_stats(
            _nearest_distances(active_centroids, network_geometries),
            prefix="sim_to_network",
        )
        network_to_sim = _distance_stats(
            _nearest_distances(network_centroids, active_polygons),
            prefix="network_to_sim",
        )
        sim_mean = _finite_mean(sim_to_network["sim_to_network_distance_mean_m"])
        network_mean = _finite_mean(network_to_sim["network_to_sim_distance_mean_m"])
        if sim_mean is None or network_mean is None:
            bidirectional_mean = None
            bidirectional_quadratic_mean = None
            bidirectional_absolute_difference_m = None
            distance_ratio = None
            distance_log10_ratio = None
        else:
            bidirectional_mean = float(0.5 * (sim_mean + network_mean))
            bidirectional_quadratic_mean = float(np.hypot(sim_mean, network_mean))
            bidirectional_absolute_difference_m = float(abs(sim_mean - network_mean))
            if sim_mean == 0.0 and network_mean == 0.0:
                distance_ratio = 1.0
                distance_log10_ratio = 0.0
            elif network_mean > 0.0 and sim_mean > 0.0:
                distance_ratio = float(sim_mean / network_mean)
                distance_log10_ratio = float(np.log10(distance_ratio))
            else:
                distance_ratio = None
                distance_log10_ratio = None
        return {
            "network_role": "reference",
            "source_variable": variable,
            "threshold": float(threshold),
            "mode": resolved_mode,
            "persistence_threshold": float(persistence_threshold),
            "timestep": int(timestep) if timestep is not None else -1,
            "network_buffer_m": float(network_buffer_m),
            "distance_method": "planar_cell_centroid_to_external_network",
            "catchment_cell_count": int(valid.sum()),
            "active_cell_count": int(active.sum()),
            "network_cell_count": int(network_cells.sum()),
            **sim_to_network,
            **network_to_sim,
            "bidirectional_distance_mean_m": bidirectional_mean,
            "bidirectional_distance_quadratic_mean_m": bidirectional_quadratic_mean,
            "bidirectional_distance_absolute_difference_m": bidirectional_absolute_difference_m,
            "planar_distance_ratio": distance_ratio,
            "planar_distance_log10_ratio": distance_log10_ratio,
        }

    def _context_watershed_gdf(self):
        if self._context_watershed_cache is not None:
            return self._context_watershed_cache

        path = self.config.context_watershed_path
        if path is None:
            self._context_watershed_cache = None
            return None
        path = Path(path)
        if not path.exists():
            self._context_watershed_cache = None
            return None

        try:
            import geopandas as gpd

            gdf = gpd.read_file(path)
        except Exception:
            gdf = None
        self._context_watershed_cache = gdf
        return gdf

    def _context_dem_path(self) -> Path | None:
        path = self.config.context_watershed_path
        if path is None:
            return None
        path = Path(path)
        candidates = (
            path.parent / "watershed_box_buff_dem.tif",
            path.parent / "context_dem.tif",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _run_topography(self, run):
        import numpy as np

        dem = np.asarray(run.dem, dtype="float64")
        dem = np.where(np.isfinite(dem), dem, np.nan)
        grid = run.grid
        extent = (
            float(grid.extent[0]),
            float(grid.extent[1]),
            float(grid.extent[2]),
            float(grid.extent[3]),
        )
        return dem, extent

    def _context_topography_layers(self, run):
        import numpy as np

        layers = [self._run_topography(run)]
        dem_path = self._context_dem_path()
        if dem_path is not None:
            try:
                import rasterio

                with rasterio.open(dem_path) as src:
                    data = src.read(1, masked=True).astype("float64")
                    dem = data.filled(np.nan)
                    bounds = src.bounds
                    extent = (
                        float(bounds.left),
                        float(bounds.right),
                        float(bounds.bottom),
                        float(bounds.top),
                    )
                layers.append((dem, extent))
            except Exception:
                pass

        return [
            (np.where(np.isfinite(dem), dem, np.nan), extent)
            for dem, extent in layers
        ]

    @staticmethod
    def _project_for_plot(gdf, fallback_crs=None):
        if gdf is None or gdf.empty:
            return gdf
        from hydromodpy.display.figures.hydrographic_network import (
            _project_gdf_for_metric_operations,
        )

        return _project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)

    def _run_watershed_gdf(self, run):
        try:
            return run.geographic("watershed")
        except Exception:
            return None

    def _plot_watershed_context(self, ax, run) -> str:
        from hydromodpy.display._map_axes import overlay_watershed_contour

        context_watershed = self._context_watershed_gdf()
        if context_watershed is not None and not context_watershed.empty:
            fallback = self._run_watershed_gdf(run)
            fallback_crs = None if fallback is None or fallback.empty else fallback.crs
            context_watershed = self._project_for_plot(
                context_watershed,
                fallback_crs=fallback_crs,
            )
            if context_watershed is not None and not context_watershed.empty:
                context_watershed.boundary.plot(
                    ax=ax,
                    color="#111827",
                    linewidth=1.35,
                    alpha=0.95,
                    zorder=7,
                )
                return "external"

        try:
            overlay_watershed_contour(ax, run, color="#111827", linewidth=1.15, alpha=0.9)
        except Exception:
            return "none"
        return "support"

    def _overlay_reference(self, ax, run, reference_gdf=None) -> None:
        from matplotlib.lines import Line2D

        has_reference = False
        try:
            reference = run.hydrographic_network("reference")
        except Exception:
            reference = reference_gdf
        if reference is not None and not reference.empty:
            watershed = self._run_watershed_gdf(run)
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
            reference = self._project_for_plot(reference, fallback_crs=fallback_crs)
            reference.plot(ax=ax, color="#9b1c1c", linewidth=1.25, alpha=0.98, zorder=6)
            has_reference = True
        watershed_context = self._plot_watershed_context(ax, run)
        if has_reference or watershed_context != "none":
            handles = []
            if has_reference:
                handles.append(Line2D([0], [0], color="#9b1c1c", lw=1.6, label="reseau observe"))
            if watershed_context == "external":
                handles.append(
                    Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant")
                )
            elif watershed_context == "support":
                handles.append(
                    Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant")
                )
            ax.legend(
                handles=handles,
                loc="upper right",
                frameon=True,
                framealpha=0.9,
                fontsize=8,
            )

    @staticmethod
    def _remove_map_frame(ax) -> None:
        """Keep map coordinates, but avoid a second visual frame inside the HTML card."""
        for spine in ax.spines.values():
            spine.set_visible(False)

    def _reference_network_for_run(self, run):
        try:
            reference = run.hydrographic_network("reference")
            if reference is not None and not reference.empty:
                return reference
        except Exception:
            pass
        fallback = self._fallback_reference_network()
        if fallback is None or fallback.empty:
            return None
        return fallback

    def _render_log_flux_figure(
        self,
        run,
        *,
        variable: str,
        title: str,
        save_path: Path,
        reference_gdf=None,
    ) -> None:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.ticker import FormatStrFormatter, MaxNLocator

        from hydromodpy.display._map_axes import style_map_axes
        from hydromodpy.display._ugrid import render_face_field

        values = self._log10_positive(self._mean_positive_flux(run, variable))
        finite = values[np.isfinite(values)]
        if finite.size:
            vmin = float(np.nanpercentile(finite, 5.0))
            vmax = float(np.nanpercentile(finite, 95.0))
            if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
                vmin = float(np.nanmin(finite))
                vmax = float(np.nanmax(finite))
        else:
            vmin, vmax = -12.0, 0.0

        fig, ax = plt.subplots(figsize=(7.8, 5.8), dpi=180, constrained_layout=True)
        collection = render_face_field(
            ax,
            run,
            values,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            cbar_label="log10(flux moyen positif)",
        )
        ticks = np.linspace(float(vmin), float(vmax), 5)
        tick_labels = [f"{tick:.1f}" for tick in ticks]
        colorbar = getattr(collection, "colorbar", None)
        if colorbar is not None:
            colorbar.set_ticks(ticks)
            colorbar.set_ticklabels(tick_labels)
        elif len(fig.axes) > 1:
            fig.axes[-1].yaxis.set_major_locator(MaxNLocator(nbins=5))
            fig.axes[-1].yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
        self._overlay_reference(ax, run, reference_gdf=reference_gdf)
        style_map_axes(ax)
        self._remove_map_frame(ax)
        ax.set_title(title)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=180, bbox_inches="tight")
        plt.close(fig)

    def _load_recharge_config(self, path: Path, seen: set[Path] | None = None) -> dict[str, object]:
        seen = seen or set()
        path = path.resolve()
        if path in seen:
            return {}
        seen.add(path)
        config = self.read_toml(path)
        data = config.get("data", {})
        if isinstance(data, dict):
            recharge = data.get("recharge", {})
            if isinstance(recharge, dict) and recharge.get("sources"):
                return config

        nested: list[str] = []
        comparison = config.get("comparison", {})
        if isinstance(comparison, dict) and isinstance(
            comparison.get("base_simulation_config"), str
        ):
            nested.append(str(comparison["base_simulation_config"]))
        if isinstance(config.get("base_config"), str):
            nested.append(str(config["base_config"]))
        for raw_path in nested:
            child = (path.parent / raw_path).resolve()
            found = self._load_recharge_config(child, seen)
            if found:
                return found
        return {}

    def _first_recharge_source(self) -> dict[str, object]:
        if self.config.base_config is None:
            return {}
        config = self._load_recharge_config(Path(self.config.base_config))
        data = config.get("data", {})
        if not isinstance(data, dict):
            return {}
        recharge = data.get("recharge", {})
        if not isinstance(recharge, dict):
            return {}
        sources = recharge.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return {}
        source = sources[0]
        return source if isinstance(source, dict) else {}

    def recharge_values_from_config(self) -> list[float]:
        source = self._first_recharge_source()
        values = source.get("values", [])
        if not isinstance(values, list):
            values = [values] if values not in ("", None) else []
        parsed: list[float] = []
        for value in values:
            try:
                parsed.append(float(value))
            except (TypeError, ValueError):
                continue
        return parsed

    @staticmethod
    def _add_months(start: date, months: int) -> date:
        month_index = start.month - 1 + int(months)
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        return date(year, month, 1)

    def recharge_month_labels(self, n_values: int) -> list[str]:
        source = self._first_recharge_source()
        raw_start = source.get("start_date") or "2000-01-01"
        if isinstance(raw_start, date):
            start = raw_start
        else:
            start = date.fromisoformat(str(raw_start)[:10])
        return [f"{self._add_months(start, index):%b} {self._add_months(start, index).year}" for index in range(n_values)]

    def recharge_summary_text(self) -> str:
        values = self.recharge_values_from_config()
        if not values:
            return "chronique de recharge non trouvee"
        return (
            f"{len(values)} mois; moyenne {sum(values) / len(values):.2f} mm/j; "
            f"min {min(values):.2f}; max {max(values):.2f}"
        )

    def generate_recharge_figure(self) -> bool:
        values = self.recharge_values_from_config()
        if not values:
            return False

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        labels = self.recharge_month_labels(len(values))
        mean_value = sum(values) / len(values)
        fig, ax = plt.subplots(figsize=(6.6, 1.9), dpi=180, constrained_layout=True)
        x_values = list(range(len(values)))
        ax.bar(x_values, values, color="#4c78a8", width=0.72)
        ax.axhline(mean_value, color="#b23a48", linewidth=1.2, linestyle="--", label="moyenne")
        ax.set_title("Recharge mensuelle imposee", fontsize=10)
        ax.set_ylabel("mm/j")
        ax.set_xticks(x_values)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        ax.grid(axis="y", color="#d8dee6", linewidth=0.7, alpha=0.8)
        ax.legend(loc="upper right", frameon=False, fontsize=8)
        ax.tick_params(axis="y", labelsize=8)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        self.recharge_figure_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(self.recharge_figure_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return True

    def generate_context_figure(self, records: list[SimulationRecord]) -> bool:
        try:
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            return False

        for record in records:
            source_row = self._source_row(record)
            run_folder = source_row.get("run_folder", "")
            sim_id = source_row.get("sim_id", "")
            if not run_folder or not sim_id:
                continue
            catalog = None
            try:
                catalog = SimulationCatalog(resolve_recorded_path(run_folder))
                run = catalog[str(sim_id)]
                self._render_topographic_context_figure(run)
                return True
            except Exception:
                continue
            finally:
                if catalog is not None:
                    try:
                        catalog.close()
                    except Exception:
                        pass
        return False

    def _render_topographic_context_figure(self, run) -> None:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.lines import Line2D

        from hydromodpy.display._map_axes import style_map_axes

        layers = self._context_topography_layers(run)
        finite_values = [
            dem[np.isfinite(dem)]
            for dem, _extent in layers
            if dem[np.isfinite(dem)].size
        ]
        finite = np.concatenate(finite_values) if finite_values else np.asarray([])
        if finite.size:
            vmin = float(np.nanpercentile(finite, 2.0))
            vmax = float(np.nanpercentile(finite, 98.0))
        else:
            vmin, vmax = 0.0, 1.0

        fig, ax = plt.subplots(figsize=(8.2, 6.1), dpi=180, constrained_layout=True)
        image = None
        for index, (dem, extent) in enumerate(layers):
            image = ax.imshow(
                dem,
                extent=extent,
                origin="upper",
                cmap="terrain",
                vmin=vmin,
                vmax=vmax,
                zorder=1 + index,
            )
        if image is None:
            return
        colorbar = fig.colorbar(image, ax=ax, fraction=0.042, pad=0.015)
        colorbar.set_label("altitude (m)")
        colorbar.ax.tick_params(labelsize=8)

        reference = self._reference_network_for_run(run)
        has_reference = False
        if reference is not None and not reference.empty:
            watershed = self._run_watershed_gdf(run)
            fallback_crs = None if watershed is None or watershed.empty else watershed.crs
            reference = self._project_for_plot(reference, fallback_crs=fallback_crs)
            reference.plot(ax=ax, color="#9b1c1c", linewidth=1.25, alpha=0.98, zorder=6)
            has_reference = True

        watershed_context = self._plot_watershed_context(ax, run)
        handles = []
        if has_reference:
            handles.append(Line2D([0], [0], color="#9b1c1c", lw=1.6, label="reseau observe"))
        if watershed_context == "external":
            handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
        elif watershed_context == "support":
            handles.append(Line2D([0], [0], color="#111827", lw=1.4, label="limite bassin versant"))
        if handles:
            ax.legend(handles=handles, loc="upper right", frameon=True, framealpha=0.92, fontsize=8)
        style_map_axes(ax)
        self._remove_map_frame(ax)
        ax.set_title("Contexte topographique")
        self.context_figure_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(self.context_figure_path, dpi=180, bbox_inches="tight")
        plt.close(fig)

    @staticmethod
    def short_configuration_label(record: SimulationRecord) -> str:
        return record.meta.short_label or record.meta.label

    def generate_metric_synthesis_figure(self, records: list[SimulationRecord]) -> bool:
        items: list[tuple[str, float | None, float | None, float | None, float | None]] = []
        for record in records:
            release = record.release_distance
            routed = self.routed_distance(record)
            release_distance = _parse_float(_row_value(release, "bidirectional_distance_mean_m"))
            routed_distance_mean = _parse_float(
                _row_value(routed, "bidirectional_distance_mean_m")
            )
            release_ratio = _parse_float(_row_value(release, "planar_distance_ratio"))
            routed_ratio = _parse_float(_row_value(routed, "planar_distance_ratio"))
            if any(
                value is not None
                for value in (release_distance, routed_distance_mean, release_ratio, routed_ratio)
            ):
                items.append(
                    (
                        self.short_configuration_label(record),
                        release_distance,
                        routed_distance_mean,
                        release_ratio,
                        routed_ratio,
                    )
                )
        if not items:
            return False

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np

        labels = [item[0] for item in items]
        y_values = np.arange(len(items), dtype=float)
        release_distances = [item[1] for item in items]
        routed_distances = [item[2] for item in items]
        release_ratios = [item[3] for item in items]
        routed_ratios = [item[4] for item in items]

        fig, axes = plt.subplots(
            1,
            2,
            figsize=(9.4, 3.8),
            dpi=180,
            sharey=True,
            constrained_layout=True,
        )
        styles = (
            ("Emergences avant routage", "#4c78a8", "o"),
            ("Emergences accumulees vers l'aval", "#f58518", "s"),
        )
        for ax, title, xlabel, first, second in (
            (axes[0], "Distance moyenne symetrique", "m", release_distances, routed_distances),
            (axes[1], "Ratio des distances", "calc -> obs / obs -> calc", release_ratios, routed_ratios),
        ):
            for values, (method_label, color, marker), offset in (
                (first, styles[0], -0.12),
                (second, styles[1], 0.12),
            ):
                xs = [float(value) if value is not None else np.nan for value in values]
                ax.scatter(xs, y_values + offset, label=method_label, color=color, marker=marker, s=34)
                for x_value, y_value in zip(xs, y_values + offset, strict=True):
                    if np.isfinite(x_value):
                        label = f" {x_value:.0f}" if xlabel == "m" else f" {x_value:.2f}"
                        ax.text(x_value, y_value, label, va="center", fontsize=7)
            ax.set_title(title, fontsize=10)
            ax.set_xlabel(xlabel)
            ax.grid(axis="x", color="#d8dee6", linewidth=0.7, alpha=0.8)
            ax.tick_params(labelsize=8)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
        axes[0].set_yticks(y_values)
        axes[0].set_yticklabels(labels, fontsize=8)
        axes[0].invert_yaxis()
        axes[1].axvline(1.0, color="#808b96", linewidth=1.0, linestyle="--")
        axes[0].legend(loc="lower right", frameon=False, fontsize=8)

        self.metric_synthesis_figure_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(self.metric_synthesis_figure_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return True

    def _distance_csv_fieldnames(self) -> list[str]:
        source = self.comparison_root / "release_flux_network_distance_metrics.csv"
        if source.exists():
            with source.open("r", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames:
                    return list(reader.fieldnames)
        return [
            "comparison_id",
            "simulation_id",
            "simulation_label",
            "solver",
            "mesh_label",
            "mesh_mode",
            "sim_id",
            "run_name",
            "run_folder",
            "network_role",
            "source_variable",
            "threshold",
            "mode",
            "persistence_threshold",
            "timestep",
            "network_buffer_m",
            "distance_method",
            "catchment_cell_count",
            "active_cell_count",
            "network_cell_count",
            "sim_to_network_sample_count",
            "sim_to_network_distance_mean_m",
            "network_to_sim_sample_count",
            "network_to_sim_distance_mean_m",
            "bidirectional_distance_mean_m",
            "planar_distance_ratio",
            "planar_distance_log10_ratio",
        ]

    def _write_distance_rows(self, path: Path, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        fieldnames = self._distance_csv_fieldnames()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _distance_csv_matches_current_runs(
        self,
        path: Path,
        records: list[SimulationRecord],
    ) -> bool:
        rows = self.read_csv(path)
        if not rows:
            return False
        current_by_sim = {
            record.meta.simulation_id: record.run_info.get("sim_id", "")
            for record in records
            if record.run_info.get("sim_id")
        }
        for row in rows:
            simulation_id = row.get("simulation_id", "")
            current_sim_id = current_by_sim.get(simulation_id)
            if current_sim_id and row.get("sim_id", "") != current_sim_id:
                return False
        return True

    def generate_missing_distance_metrics(self, records: list[SimulationRecord]) -> int:
        try:
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            return 0

        manifest = self.read_json(self.comparison_root / "comparison_manifest.json")
        comparison_id = self.config.comparison_id or str(
            manifest.get("comparison_id") or self.comparison_root.name
        )
        generated = 0

        outputs = (
            (
                "release_flux_network_distance_metrics.csv",
                "release_flux",
                "release_distance",
            ),
            (
                "simulated_active_network_distance_metrics.csv",
                "accumulation_flux",
                "accumulation_distance",
            ),
            (
                "release_accumulation_network_distance_metrics.csv",
                "release_accumulation_flux",
                "release_accumulation_distance",
            ),
        )
        fallback_reference = None
        for filename, variable, attr in outputs:
            output_path = self.comparison_root / filename
            if output_path.exists() and self._distance_csv_matches_current_runs(output_path, records):
                continue
            rows: list[dict[str, str]] = []
            for record in records:
                source_row = self._source_row(record)
                run_folder = source_row.get("run_folder", "")
                sim_id = source_row.get("sim_id", "")
                if not run_folder or not sim_id:
                    continue
                catalog = None
                try:
                    catalog = SimulationCatalog(resolve_recorded_path(run_folder))
                    run = catalog[str(sim_id)]
                    if not run.has_field(variable):
                        continue
                    if run.has_hydrographic_network("reference"):
                        metrics = run.cell_field_network_distance_metrics(
                            network_role="reference",
                            variable=variable,
                            threshold=0.0,
                            mode=None,
                            persistence_threshold=0.5,
                            timestep=None,
                            network_buffer_m=0.0,
                        )
                    else:
                        if fallback_reference is None:
                            fallback_reference = self._fallback_reference_network()
                        if fallback_reference is None or fallback_reference.empty:
                            continue
                        metrics = self._distance_metrics_with_external_network(
                            run,
                            fallback_reference,
                            variable=variable,
                            threshold=0.0,
                            mode=None,
                            persistence_threshold=0.5,
                            timestep=None,
                            network_buffer_m=0.0,
                        )
                    row = {
                        "comparison_id": comparison_id,
                        "simulation_id": record.meta.simulation_id,
                        "simulation_label": record.simulation_label or record.meta.label,
                        "solver": record.solver,
                        "mesh_label": record.mesh_label,
                        "mesh_mode": record.mesh_mode,
                        "sim_id": str(sim_id),
                        "run_name": source_row.get("run_name", ""),
                        "run_folder": run_folder,
                    }
                    row.update(
                        {
                            key: str(value if value is not None else "")
                            for key, value in metrics.items()
                        }
                    )
                    setattr(record, attr, row)
                    rows.append(row)
                    generated += 1
                except Exception:
                    continue
                finally:
                    if catalog is not None:
                        try:
                            catalog.close()
                        except Exception:
                            pass
            self._write_distance_rows(output_path, rows)
        return generated

    def generate_field_figures(self, records: list[SimulationRecord]) -> int:
        try:
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            return 0

        generated = 0
        fallback_reference = None
        for record in records:
            source_row = self._source_row(record)
            run_folder = source_row.get("run_folder", "")
            sim_id = source_row.get("sim_id", "")
            if not run_folder or not sim_id:
                continue
            catalog = None
            try:
                catalog = SimulationCatalog(resolve_recorded_path(run_folder))
                run = catalog[str(sim_id)]
                for variable, title in (
                    ("release_flux", "Emergences avant routage - intensite moyenne positive"),
                    (
                        "release_accumulation_flux",
                        "Emergences accumulees vers l'aval - intensite moyenne positive",
                    ),
                ):
                    if not run.has_field(variable):
                        continue
                    reference_gdf = None
                    if not run.has_hydrographic_network("reference"):
                        if fallback_reference is None:
                            fallback_reference = self._fallback_reference_network()
                        if fallback_reference is None or fallback_reference.empty:
                            continue
                        reference_gdf = fallback_reference
                    out = self.figure_path(record, variable)
                    self._render_log_flux_figure(
                        run,
                        variable=variable,
                        title=title,
                        save_path=out,
                        reference_gdf=reference_gdf,
                    )
                    generated += 1
            except Exception:
                continue
            finally:
                if catalog is not None:
                    try:
                        catalog.close()
                    except Exception:
                        pass
        return generated

    def contract_section(self) -> str:
        if not self.config.contract_cards:
            return ""
        cards = "".join(
            f"<article><h3>{_safe(card.title)}</h3><p>{card.body_html}</p></article>"
            for card in self.config.contract_cards
        )
        return f"""
<section>
  <h2>Contrat physique commun</h2>
  <div class="cards">{cards}</div>
</section>
"""

    def context_section(self) -> str:
        if not self.context_figure_path.exists():
            return ""
        rel = self.relative_path(self.context_figure_path)
        title = "Contexte topographique"
        return f"""
<section>
  <h2>Contexte spatial</h2>
  <p>Carte topographique du support de calcul, avec le reseau hydrographique observe en rouge et la limite du bassin versant.</p>
  <figure class="wide-figure context-figure">
    <a href="{_safe(rel)}" class="figure-link" data-lightbox-src="{_safe(rel)}" data-lightbox-title="{_safe(title)}" title="Cliquer pour agrandir">
      <img src="{_safe(rel)}" alt="{_safe(title)}" loading="lazy">
    </a>
    <figcaption>{_safe(title)}</figcaption>
  </figure>
</section>
"""

    def recharge_section(self) -> str:
        if not self.recharge_figure_path.exists():
            return ""
        rel = self.relative_path(self.recharge_figure_path)
        title = "Recharge mensuelle imposee"
        return f"""
<section>
  <h2>Recharge imposee</h2>
  <p>{_safe(self.recharge_summary_text())}. Cette chronique est commune aux configurations de ce benchmark.</p>
  <figure class="wide-figure">
    <a href="{_safe(rel)}" class="figure-link" data-lightbox-src="{_safe(rel)}" data-lightbox-title="{_safe(title)}" title="Cliquer pour agrandir">
      <img src="{_safe(rel)}" alt="{_safe(title)}" loading="lazy">
    </a>
    <figcaption>{_safe(title)}</figcaption>
  </figure>
</section>
"""

    def group_section(self, records: list[SimulationRecord], section: GroupSection) -> str:
        return f"""
<section>
  <h2>{_safe(section.title)}</h2>
  <p>{_safe(section.intro)}</p>
  {self.comparison_table(records, group=section.group_id)}
</section>
"""

    def interpretation_section(self) -> str:
        if not self.config.interpretation_cards:
            return ""
        cards = "".join(
            f"<article><h3>{_safe(card.title)}</h3><p>{card.body_html}</p></article>"
            for card in self.config.interpretation_cards
        )
        return f"""
<section>
  <h2>Lecture des ecarts regulier / irregulier</h2>
  <p>Les fortes differences viennent surtout du support geometrique utilise pour porter les sorties de nappe et pour mesurer les distances.</p>
  <div class="cards">{cards}</div>
</section>
"""

    def metric_synthesis_section(self) -> str:
        if not self.metric_synthesis_figure_path.exists():
            return ""
        rel = self.relative_path(self.metric_synthesis_figure_path)
        title = "Synthese des distances au reseau observe"
        return f"""
<section>
  <h2>Synthese des metriques</h2>
  <p>La figure compare, pour chaque configuration, les deux diagnostics de reseau avec la distance moyenne symetrique et le ratio directionnel.</p>
  <figure class="wide-figure synthesis-figure">
    <a href="{_safe(rel)}" class="figure-link" data-lightbox-src="{_safe(rel)}" data-lightbox-title="{_safe(title)}" title="Cliquer pour agrandir">
      <img src="{_safe(rel)}" alt="{_safe(title)}" loading="lazy">
    </a>
    <figcaption>{_safe(title)}</figcaption>
  </figure>
</section>
"""

    def links_section(self) -> str:
        manifest = self.read_json(self.comparison_root / "comparison_manifest.json")
        report = self.comparison_root / "web" / "index.html"
        audit = self.comparison_root / "comparison_audit.md"
        report_item = (
            f'<a href="{_safe(self.relative_path(report))}">Rapport HTML complet</a>'
            if report.exists()
            else "Rapport HTML complet non encore produit"
        )
        audit_item = (
            f'<a href="{_safe(self.relative_path(audit))}">Audit de comparaison</a>'
            if audit.exists()
            else "Audit de comparaison non encore produit"
        )
        return f"""
<section>
  <h2>Sorties completes</h2>
  <p>Cette page est volontairement compacte. Les artefacts complets restent disponibles dans le dossier de comparaison.</p>
  <ul>
    <li>{report_item}</li>
    <li>{audit_item}</li>
    <li><code>{_safe(str(self.comparison_root))}</code></li>
    <li>statut audit: <strong>{_safe(manifest.get('audit_status', 'non lance'))}</strong></li>
  </ul>
</section>
"""

    @staticmethod
    def lightbox_markup() -> str:
        return """
<div class="lightbox" id="figure-lightbox" hidden>
  <button type="button" class="lightbox-close">Fermer</button>
  <img alt="">
  <p></p>
</div>
"""

    @staticmethod
    def lightbox_script() -> str:
        return """
<script>
(() => {
  const lightbox = document.getElementById("figure-lightbox");
  if (!lightbox) return;
  const image = lightbox.querySelector("img");
  const caption = lightbox.querySelector("p");
  const closeButton = lightbox.querySelector("button");
  const close = () => {
    lightbox.hidden = true;
    image.removeAttribute("src");
    caption.textContent = "";
  };
  document.querySelectorAll("[data-lightbox-src]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      image.src = link.dataset.lightboxSrc;
      image.alt = link.dataset.lightboxTitle || "";
      caption.textContent = link.dataset.lightboxTitle || "";
      lightbox.hidden = false;
    });
  });
  closeButton.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !lightbox.hidden) close();
  });
})();
</script>
"""

    @staticmethod
    def css() -> str:
        return """
:root {
  color-scheme: light;
  --text: #1f2933;
  --muted: #627080;
  --line: #d8dee6;
  --soft: #f5f7fa;
  --panel: #ffffff;
  --accent-soft: #d7edf1;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  color: var(--text);
  background: #eef2f5;
}
main {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px;
}
h1 { margin: 0 0 8px; font-size: 30px; }
h2 { margin: 30px 0 10px; font-size: 21px; }
h3 { margin: 20px 0 8px; font-size: 15px; }
p { max-width: 980px; line-height: 1.45; color: var(--muted); }
a { color: #0f5f6f; }
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin: 16px 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
article {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--soft);
}
article h3 { margin-top: 0; }
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 14px;
}
.comparison-table th:nth-child(1) { width: 24%; }
.comparison-table th:nth-child(2),
.comparison-table th:nth-child(3) { width: 38%; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 10px 9px;
  text-align: left;
  vertical-align: top;
}
th {
  color: #33404d;
  background: var(--soft);
  font-weight: 700;
}
th span, .sub {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  margin-top: 3px;
}
.missing { color: var(--muted); background: #fafafa; }
.bar {
  height: 6px;
  border-radius: 999px;
  background: var(--accent-soft);
  margin: 0 0 6px;
}
.method-cell p {
  margin: 4px 0 9px;
  font-size: 12px;
  line-height: 1.35;
}
.method-title {
  font-weight: 700;
  color: #26313c;
}
figure {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
img { display: block; width: 100%; height: auto; }
.figure-link {
  display: block;
  cursor: zoom-in;
}
figcaption {
  padding: 9px 11px;
  color: var(--muted);
  font-size: 13px;
}
.wide-figure { max-width: 720px; }
.context-figure { max-width: 860px; }
.figure-missing {
  color: var(--muted);
  background: repeating-linear-gradient(
    -45deg,
    #fafafa,
    #fafafa 8px,
    #f1f3f5 8px,
    #f1f3f5 16px
  );
  font-style: italic;
  text-align: center;
  vertical-align: middle;
  min-height: 140px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.metric-box {
  margin-top: 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: #fbfcfd;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.metric-grid span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.metric-grid strong { font-size: 16px; }
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  padding: 18px;
  background: rgba(15, 23, 32, 0.82);
}
.lightbox[hidden] { display: none; }
.lightbox img {
  max-width: min(1400px, 96vw);
  max-height: 84vh;
  width: auto;
  height: auto;
  align-self: center;
  justify-self: center;
  border-radius: 8px;
  background: #fff;
}
.lightbox p {
  justify-self: center;
  margin: 0;
  color: #fff;
}
.lightbox-close {
  justify-self: end;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 6px;
  padding: 7px 10px;
  color: #fff;
  background: rgba(255, 255, 255, 0.12);
  cursor: pointer;
}
@media (max-width: 900px) {
  main { padding: 14px; }
  .cards { grid-template-columns: 1fr; }
  table { display: block; overflow-x: auto; }
}
"""

    def render_page(self, records: list[SimulationRecord]) -> str:
        if not any(record.release_distance or record.accumulation_distance for record in records):
            not_run = """
<section>
  <h2>Pas encore de sorties</h2>
  <p>Le benchmark n'a pas encore ete execute, ou les CSV de comparaison ne sont pas presents.</p>
</section>
"""
        else:
            not_run = ""
        groups = "".join(self.group_section(records, section) for section in self.config.group_sections)
        return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_safe(self.config.title)}</title>
  <style>{self.css()}</style>
</head>
<body>
<main>
  <h1>{_safe(self.config.title)}</h1>
  <p>{_safe(self.config.intro)}</p>
  {self.contract_section()}
  {self.context_section()}
  {self.recharge_section()}
  {not_run}
  {groups}
  {self.interpretation_section()}
  {self.metric_synthesis_section()}
  {self.links_section()}
</main>
{self.lightbox_markup()}
{self.lightbox_script()}
</body>
</html>
"""

    def build_page(self) -> Path:
        records = self.records_by_simulation()
        generated_metrics = self.generate_missing_distance_metrics(records)
        if generated_metrics:
            records = self.records_by_simulation()
        generated_context = self.generate_context_figure(records)
        generated_recharge = self.generate_recharge_figure()
        generated_synthesis = self.generate_metric_synthesis_figure(records)
        generated_figures = self.generate_field_figures(records)
        self.page_path.parent.mkdir(parents=True, exist_ok=True)
        self.page_path.write_text(self.render_page(records), encoding="utf-8")
        print(f"Wrote {self.page_path}")
        print(f"Rows: {len(records)}")
        print(f"Release-accumulation metric rows generated: {generated_metrics}")
        print(f"Context figure generated: {generated_context}")
        print(f"Recharge figure generated: {generated_recharge}")
        print(f"Metric synthesis figure generated: {generated_synthesis}")
        print(f"Field figures generated: {generated_figures}")
        return self.page_path


def build_compact_network_synthesis(config: CompactNetworkSynthesisConfig) -> Path:
    return CompactNetworkSynthesisBuilder(config).build_page()
