"""Orchestrator class that wires the IO, network, maps and sections modules."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from . import maps, network, sections
from .io import (
    CompactNetworkSynthesisConfig,
    SimulationMeta,
    SimulationRecord,
    _first,
    _parse_float,
    read_csv_rows,
    read_json_mapping,
    resolve_recorded_path,
)


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
        self._context_watershed_cache: dict[str, object] = {}
        self._fallback_reference_cache: dict[str, object] = {}

    # --- record assembly -------------------------------------------------

    def _record_for(
        self,
        records: dict[str, SimulationRecord],
        simulation_id: str,
    ) -> SimulationRecord:
        meta = self.meta_by_id.get(
            simulation_id,
            SimulationMeta(simulation_id, simulation_id, "autres"),
        )
        return records.setdefault(simulation_id, SimulationRecord(meta=meta))

    def records_by_simulation(self) -> list[SimulationRecord]:
        records: dict[str, SimulationRecord] = {}
        manifest = read_json_mapping(self.comparison_root / "comparison_manifest.json")
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
                    str(key): "" if value is None else str(value) for key, value in item.items()
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
            for row in read_csv_rows(self.comparison_root / filename):
                simulation_id = _first(row, "simulation_id")
                if not simulation_id:
                    continue
                record = self._record_for(records, simulation_id)
                record.simulation_label = record.simulation_label or _first(row, "simulation_label")
                record.solver = record.solver or _first(row, "solver")
                record.mesh_mode = record.mesh_mode or _first(row, "mesh_mode")
                record.mesh_label = record.mesh_label or _first(row, "mesh_label")
                setattr(record, attr, row)

        for row in read_csv_rows(self.comparison_root / "numerical_closure_summary.csv"):
            simulation_id = _first(row, "simulation_id")
            if not simulation_id:
                continue
            record = self._record_for(records, simulation_id)
            record.simulation_label = record.simulation_label or _first(row, "simulation_label")
            record.solver = record.solver or _first(row, "solver")
            record.closure = row

        if self.config.simulations:
            ordered = [
                self._record_for(records, meta.simulation_id) for meta in self.config.simulations
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

    def _fallback_reference_network(self):
        return network.fallback_reference_network(
            self.comparison_root,
            cache_ref=self._fallback_reference_cache,
        )

    def _reference_for_run(self, run):
        return network.reference_network_for_run(run, self._fallback_reference_network)

    # --- distance metrics CSVs ------------------------------------------

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
        rows = read_csv_rows(path)
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

        manifest = read_json_mapping(self.comparison_root / "comparison_manifest.json")
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
            if output_path.exists() and self._distance_csv_matches_current_runs(
                output_path, records
            ):
                continue
            rows: list[dict[str, str]] = []
            for record in records:
                src_row = sections.source_row(record)
                run_folder = src_row.get("run_folder", "")
                sim_id = src_row.get("sim_id", "")
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
                        metrics = network.distance_metrics_with_external_network(
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
                        "run_name": src_row.get("run_name", ""),
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

    # --- figure generation ----------------------------------------------

    def generate_context_figure(self, records: list[SimulationRecord]) -> bool:
        try:
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            return False

        for record in records:
            src_row = sections.source_row(record)
            run_folder = src_row.get("run_folder", "")
            sim_id = src_row.get("sim_id", "")
            if not run_folder or not sim_id:
                continue
            catalog = None
            try:
                catalog = SimulationCatalog(resolve_recorded_path(run_folder))
                run = catalog[str(sim_id)]
                maps.render_topographic_context_figure(
                    run,
                    self.context_figure_path,
                    config_watershed_path=self.config.context_watershed_path,
                    watershed_cache=self._context_watershed_cache,
                    reference_provider=self._reference_for_run,
                )
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

    def generate_recharge_figure(self) -> bool:
        return maps.generate_recharge_figure(
            self.config.base_config,
            self.recharge_figure_path,
        )

    def generate_metric_synthesis_figure(self, records: list[SimulationRecord]) -> bool:
        return maps.generate_metric_synthesis_figure(
            records,
            self.metric_synthesis_figure_path,
            routed_distance_for=self.routed_distance,
        )

    def figure_path(self, record: SimulationRecord, variable: str) -> Path:
        return sections.figure_path(self.figure_root, record, variable)

    def generate_field_figures(self, records: list[SimulationRecord]) -> int:
        try:
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            return 0

        generated = 0
        fallback_reference = None
        for record in records:
            src_row = sections.source_row(record)
            run_folder = src_row.get("run_folder", "")
            sim_id = src_row.get("sim_id", "")
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
                    maps.render_log_flux_figure(
                        run,
                        variable=variable,
                        title=title,
                        save_path=out,
                        reference_gdf=reference_gdf,
                        config_watershed_path=self.config.context_watershed_path,
                        watershed_cache=self._context_watershed_cache,
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

    # --- page rendering -------------------------------------------------

    def render_page(self, records: list[SimulationRecord]) -> str:
        return sections.render_page(
            self.config,
            records,
            page_path=self.page_path,
            figure_root=self.figure_root,
            comparison_root=self.comparison_root,
            context_figure_path=self.context_figure_path,
            recharge_figure_path=self.recharge_figure_path,
            metric_synthesis_figure_path=self.metric_synthesis_figure_path,
            recharge_summary=maps.recharge_summary_text(self.config.base_config),
            routed_distance_for=self.routed_distance,
            all_distances=self.all_bidirectional_distances(records),
        )

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
