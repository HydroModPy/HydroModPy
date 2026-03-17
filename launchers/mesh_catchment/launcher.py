"""Dedicated launcher for catchment meshing workflows.

This launcher can run either one catchment mesh workflow or iterate over one
table of outlet coordinates and mesh each delineated catchment independently.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any

# When this file is executed directly by path, Python adds the script folder to
# ``sys.path`` but not necessarily the repository root. Insert the repo root
# explicitly so local imports always resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import _load_standard_section
from hydromodpy.config.toml_loader import load_toml_with_base_config
from hydromodpy.geographic.core.domain_geographic_pipeline import (
    build_domain_geographic_context,
)
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig
from hydromodpy.solver.utils.mesh.gmsh_grid import export_catchment_mesh_bundle
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.run_case_zone_conformal import (
    run_reference_2d_zone_conformal_case_from_toml,
)
from launchers.mesh_catchment.config import validate_mesh_catchment_batch_config_data
from launchers.mesh_catchment.runtime import (
    prepare_geographic_config_for_meshing,
    require_mesh_section,
    resolve_constraints_mode,
)


DEFAULT_CONFIG_NAME = "config_mesh_catchment_example.toml"
_VECTOR_TABLE_SUFFIXES = {".geojson", ".gpkg", ".json", ".shp"}


@dataclass(frozen=True)
class MeshCatchmentBatchOutputsConfig:
    mesh_filename: str | None = None
    summary_filename: str | None = None
    figure_filename: str | None = None
    manifest_csv: str | None = None


@dataclass(frozen=True)
class MeshCatchmentBatchConfig:
    outlets_table_path: Path
    outlet_id_column: str
    x_column: str
    y_column: str
    selection_mode: str
    selected_outlet_ids: tuple[str, ...]
    catch_name_pattern: str
    continue_on_error: bool
    outputs: MeshCatchmentBatchOutputsConfig

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
        *,
        base_dir: Path,
    ) -> MeshCatchmentBatchConfig | None:
        if raw_value is None:
            return None
        if not isinstance(raw_value, Mapping):
            raise ValueError(
                "mesh_catchment_batch configuration must be a mapping when provided."
            )
        enabled_raw = raw_value.get("enabled", False)
        if not isinstance(enabled_raw, bool):
            raise ValueError("mesh_catchment_batch.enabled must be a boolean.")
        if not enabled_raw:
            return None
        validated = validate_mesh_catchment_batch_config_data(raw_value)

        outlets_table_path = _resolve_required_path(
            validated.get("outlets_table_path"),
            label="mesh_catchment_batch.outlets_table_path",
            base_dir=base_dir,
        )
        outlet_id_column = _require_text(
            validated.get("outlet_id_column", "outlet_id"),
            label="mesh_catchment_batch.outlet_id_column",
        )
        x_column = _require_text(
            validated.get("x_column", "x_outlet_m"),
            label="mesh_catchment_batch.x_column",
        )
        y_column = _require_text(
            validated.get("y_column", "y_outlet_m"),
            label="mesh_catchment_batch.y_column",
        )

        selection_mode = str(validated.get("selection_mode", "all")).strip().lower()
        if selection_mode not in {"all", "selected"}:
            raise ValueError(
                "mesh_catchment_batch.selection_mode must be 'all' or 'selected'."
            )
        selected_outlet_ids_raw = validated.get("selected_outlet_ids", ())
        if selected_outlet_ids_raw is None:
            selected_outlet_ids_raw = ()
        if isinstance(selected_outlet_ids_raw, (str, bytes)) or not isinstance(
            selected_outlet_ids_raw,
            Sequence,
        ):
            raise ValueError(
                "mesh_catchment_batch.selected_outlet_ids must be a list when provided."
            )
        selected_outlet_ids = tuple(
            str(value).strip()
            for value in selected_outlet_ids_raw
            if str(value).strip() != ""
        )
        if selection_mode == "selected" and not selected_outlet_ids:
            raise ValueError(
                "mesh_catchment_batch.selection_mode='selected' requires one non-empty selected_outlet_ids list."
            )

        catch_name_pattern = _require_text(
            validated.get("catch_name_pattern", "{catch_name}_outlet_{outlet_id}"),
            label="mesh_catchment_batch.catch_name_pattern",
        )
        if "{outlet_id}" not in catch_name_pattern:
            raise ValueError(
                "mesh_catchment_batch.catch_name_pattern must contain '{outlet_id}'."
            )

        continue_on_error_raw = validated.get("continue_on_error", False)
        if not isinstance(continue_on_error_raw, bool):
            raise ValueError(
                "mesh_catchment_batch.continue_on_error must be a boolean."
            )

        outputs_raw = validated.get("outputs", {})
        if outputs_raw is None:
            outputs_raw = {}
        if not isinstance(outputs_raw, Mapping):
            raise ValueError("mesh_catchment_batch.outputs must be a mapping.")
        outputs = MeshCatchmentBatchOutputsConfig(
            mesh_filename=_optional_text(outputs_raw.get("mesh_filename")),
            summary_filename=_optional_text(outputs_raw.get("summary_filename")),
            figure_filename=_optional_text(outputs_raw.get("figure_filename")),
            manifest_csv=_optional_text(outputs_raw.get("manifest_csv")),
        )

        return cls(
            outlets_table_path=outlets_table_path,
            outlet_id_column=outlet_id_column,
            x_column=x_column,
            y_column=y_column,
            selection_mode=selection_mode,
            selected_outlet_ids=selected_outlet_ids,
            catch_name_pattern=catch_name_pattern,
            continue_on_error=continue_on_error_raw,
            outputs=outputs,
        )


@dataclass(frozen=True)
class MeshCatchmentOutletRecord:
    outlet_id: str
    outlet_id_safe: str
    x_outlet: float
    y_outlet: float


def _optional_text(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _require_text(raw_value: object, *, label: str) -> str:
    text = _optional_text(raw_value)
    if text is None:
        raise ValueError(f"{label} cannot be empty.")
    return text


def _resolve_required_path(
    raw_value: object,
    *,
    label: str,
    base_dir: Path,
) -> Path:
    text = _require_text(raw_value, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _sanitize_path_token(raw_value: object) -> str:
    text = str(raw_value).strip()
    if text == "":
        return "unknown"
    collapsed = re.sub(r"\s+", "_", text)
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = sanitized.strip("._-")
    return sanitized or "unknown"


def _clone_config(config: object, *, updates: Mapping[str, Any]) -> object:
    model_dump = getattr(config, "model_dump", None)
    model_validate = getattr(config.__class__, "model_validate", None)
    if callable(model_dump) and callable(model_validate):
        payload = dict(model_dump(mode="python"))
        payload.update(dict(updates))
        return config.__class__.model_validate(payload)
    payload = dict(vars(config))
    payload.update(dict(updates))
    return SimpleNamespace(**payload)


def _workspace_catch_name(workspace_like: object) -> str:
    return str(Path(workspace_like.project_root).name)


def _workspace_project_root(workspace_like: object) -> Path:
    return Path(workspace_like.project_root)


def _workspace_output_root(workspace_like: object) -> Path:
    output_root = getattr(workspace_like, "output_root", None)
    if output_root is not None:
        return Path(output_root)
    return Path(workspace_like.project_root)


def _derive_child_workspace_path(
    *,
    current_path: Path,
    current_name: str,
    child_name: str,
) -> Path:
    if current_path.name == str(current_name):
        return current_path.parent / child_name
    return current_path / child_name


def _workspace_stable_folder(workspace_like: object) -> Path:
    stable_folder = getattr(workspace_like, "stable_folder", None)
    if stable_folder is not None:
        return Path(stable_folder)
    output_root = getattr(workspace_like, "output_root", None)
    if output_root is not None:
        return Path(output_root) / "results_stable"
    return Path(workspace_like.project_root) / "results_stable"


class MeshCatchmentLauncher:
    """Run one mesh-only workflow from the ``[mesh_catchment]`` TOML section."""

    SECTION_NAME = "mesh_catchment"
    _RIVER_TRACE_CONSTRAINT_MODES = {"rivers_only", "geology_rivers"}

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = require_mesh_section(self.raw_toml)
        self.workspace_cfg, self.geographic_cfg = self._load_runtime_configs(
            self.raw_toml
        )
        self.constraints_mode = resolve_constraints_mode(
            self.mesh_section_data.get("constraints_mode")
        )
        self.geographic_cfg = prepare_geographic_config_for_meshing(
            self.geographic_cfg,
            constraints_mode=self.constraints_mode,
        )
        self.batch_cfg = MeshCatchmentBatchConfig.from_mapping(
            self.raw_toml.get("mesh_catchment_batch"),
            base_dir=self.config_path.parent,
        )
        if self.batch_cfg is not None:
            self._validate_batch_output_configuration(self.batch_cfg)

    def _normalize_workspace_section(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        base_dir = self.config_path.parent
        workspace_data = dict(payload.get("workspace", {}))

        if not workspace_data.get("project_root"):
            workspace_data["project_root"] = str(base_dir)

        return workspace_data

    def _load_runtime_configs(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[WorkspaceConfig, GeographicConfig]:
        """Load only workspace/geographic sections needed by this mesh-only launcher."""
        base_dir = self.config_path.parent
        workspace_data = self._normalize_workspace_section(payload)
        workspace_cfg = _load_standard_section(
            workspace_data,
            WorkspaceConfig,
            base_dir,
        )
        geographic_cfg = _load_standard_section(
            payload.get("geographic", {}),
            GeographicConfig,
            base_dir,
        )
        return workspace_cfg, geographic_cfg

    @classmethod
    def _resolve_constraints_mode(cls, raw_value: Any) -> str:
        token = "" if raw_value is None else str(raw_value).strip().lower()
        if token == "":
            raise ValueError(
                "mesh_catchment.constraints_mode is required and must be one of: "
                "geology_only, rivers_only, geology_rivers."
            )
        allowed = {
            "geology_only",
            "rivers_only",
            "geology_rivers",
        }
        if token not in allowed:
            raise ValueError(
                "mesh_catchment.constraints_mode must be one of: "
                "geology_only, rivers_only, geology_rivers."
            )
        return token

    @classmethod
    def _require_mesh_section(cls, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return require_mesh_section(payload, section_name=cls.SECTION_NAME)

    @classmethod
    def _constraints_mode_requires_river_trace(cls, constraints_mode: str) -> bool:
        return (
            str(constraints_mode).strip().lower()
            in cls._RIVER_TRACE_CONSTRAINT_MODES
        )

    @classmethod
    def _prepare_geographic_config_for_meshing(
        cls,
        geographic_cfg: GeographicConfig,
        *,
        constraints_mode: str,
    ) -> GeographicConfig:
        return prepare_geographic_config_for_meshing(
            geographic_cfg,
            constraints_mode=constraints_mode,
            section_name=cls.SECTION_NAME,
        )

    def _build_domain_geographic_context(self, workspace, geographic_cfg):
        """Build domain-level geographic context with optional in-memory river trace."""
        return build_domain_geographic_context(
            config=geographic_cfg,
            workspace=workspace,
        )

    def _resolve_river_trace_for_launcher(
        self,
        domain_geographic: object | None,
    ) -> object | None:
        if domain_geographic is None:
            return None
        return getattr(domain_geographic, "river_mesh_trace", None)

    def _validate_river_trace_requirement(
        self,
        *,
        geographic_cfg,
        river_trace: object | None,
    ) -> None:
        if not self._constraints_mode_requires_river_trace(self.constraints_mode):
            return
        if river_trace is not None:
            return
        if geographic_cfg.uses_synthetic_geographic():
            raise ValueError(
                "mesh_catchment.constraints_mode requires river_trace, but synthetic geographic "
                "mode does not generate river networks."
            )
        raise ValueError(
            "mesh_catchment.constraints_mode requires river_trace, but no in-memory "
            "river trace was generated. Ensure [geographic.river_network] is enabled "
            "with valid threshold parameters."
        )

    @staticmethod
    def _resolve_optional_path(
        *,
        config_dir: Path,
        raw_value: Any,
    ) -> Path | None:
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        if text == "":
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (config_dir / path).resolve()
        return path

    def _resolve_output_overrides(
        self,
        workspace,
        *,
        explicit_overrides: Mapping[str, Path | None] | None = None,
    ) -> tuple[Path, Path, Path | None, bool]:
        section = self.mesh_section_data
        config_dir = self.config_path.parent
        overrides = dict(explicit_overrides or {})
        mesh_dir = _workspace_stable_folder(workspace) / "mesh" / "gmsh"

        output_mesh = overrides.get("output_mesh")
        if output_mesh is None:
            output_mesh = self._resolve_optional_path(
                config_dir=config_dir,
                raw_value=section.get("output_mesh"),
            )
        if output_mesh is None:
            output_mesh = mesh_dir / "mesh_catchment.msh"

        output_summary_json = overrides.get("output_summary_json")
        if output_summary_json is None:
            output_summary_json = self._resolve_optional_path(
                config_dir=config_dir,
                raw_value=section.get("output_summary_json"),
            )
        if output_summary_json is None:
            output_summary_json = mesh_dir / "mesh_catchment_summary.json"

        output_figure = overrides.get("output_figure")
        if output_figure is None:
            output_figure = self._resolve_optional_path(
                config_dir=config_dir,
                raw_value=section.get("output_figure"),
            )

        raw_show_plot = section.get("show_plot", False)
        show_plot = bool(raw_show_plot) if isinstance(raw_show_plot, bool) else False
        return output_mesh, output_summary_json, output_figure, show_plot

    def _run_single_workflow(
        self,
        *,
        workspace_cfg,
        geographic_cfg,
        output_overrides: Mapping[str, Path | None] | None = None,
    ) -> dict[str, Any]:
        workspace = hmp.Workspace(config=workspace_cfg)
        domain_geographic = self._build_domain_geographic_context(workspace, geographic_cfg)
        river_trace = self._resolve_river_trace_for_launcher(domain_geographic)
        self._validate_river_trace_requirement(
            geographic_cfg=geographic_cfg,
            river_trace=river_trace,
        )

        output_mesh, output_summary_json, output_figure, show_plot = (
            self._resolve_output_overrides(
                workspace,
                explicit_overrides=output_overrides,
            )
        )

        summary = run_reference_2d_zone_conformal_case_from_toml(
            self.config_path,
            section=self.SECTION_NAME,
            output_mesh=output_mesh,
            output_summary_json=output_summary_json,
            output_figure=output_figure,
            river_trace=river_trace,
            domain_geographic=domain_geographic,
            show_plot=show_plot,
        )
        summary_dict = dict(summary)
        if Path(output_mesh).exists():
            geology_cfg = self.mesh_section_data.get("geology")
            if not isinstance(geology_cfg, Mapping):
                geology_cfg = None
            try:
                bundle_summary = export_catchment_mesh_bundle(
                    mesh_path=output_mesh,
                    domain_geographic=domain_geographic,
                    geology_cfg=geology_cfg,
                    river_trace=river_trace,
                    summary=summary_dict,
                    config_path=self.config_path,
                )
                summary_dict["exchange_bundle"] = bundle_summary
                summary_dict["output_exchange_bundle_dir"] = str(
                    bundle_summary["bundle_dir"]
                )
            except Exception as exc:
                summary_dict["exchange_bundle_error"] = str(exc)
        return summary_dict

    def _validate_batch_output_configuration(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> None:
        required_patterns = {
            "output_mesh": "mesh_filename",
            "output_summary_json": "summary_filename",
            "output_figure": "figure_filename",
        }
        for section_key, pattern_attr in required_patterns.items():
            raw_value = self.mesh_section_data.get(section_key)
            if _optional_text(raw_value) is None:
                continue
            if _optional_text(getattr(batch_cfg.outputs, pattern_attr)) is not None:
                continue
            raise ValueError(
                "Batch mode detected one fixed "
                f"mesh_catchment.{section_key} override. Configure "
                f"mesh_catchment_batch.outputs.{pattern_attr} to avoid file overwrite "
                "between outlets."
            )

    def _load_outlet_records(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> list[MeshCatchmentOutletRecord]:
        table_path = batch_cfg.outlets_table_path
        suffix = table_path.suffix.lower()
        if suffix == ".csv":
            rows = self._load_outlet_rows_from_csv(table_path)
        elif suffix in _VECTOR_TABLE_SUFFIXES:
            rows = self._load_outlet_rows_from_vector(table_path)
        else:
            raise ValueError(
                "Unsupported mesh_catchment_batch outlets table format "
                f"'{table_path.suffix}'. Supported: .csv, .shp, .gpkg, .geojson, .json."
            )
        if not rows:
            raise ValueError(
                f"mesh_catchment_batch outlets table contains no outlet row: {table_path}"
            )

        selected_ids = set(batch_cfg.selected_outlet_ids)
        records: list[MeshCatchmentOutletRecord] = []
        seen_outlet_ids: set[str] = set()
        for index, row in enumerate(rows, start=1):
            record = self._build_outlet_record(
                row=row,
                outlet_id_column=batch_cfg.outlet_id_column,
                x_column=batch_cfg.x_column,
                y_column=batch_cfg.y_column,
                row_label=f"{table_path} row {index}",
            )
            if batch_cfg.selection_mode == "selected" and record.outlet_id not in selected_ids:
                continue
            if record.outlet_id in seen_outlet_ids:
                raise ValueError(
                    "mesh_catchment_batch outlets table contains duplicated outlet_id "
                    f"'{record.outlet_id}'."
                )
            seen_outlet_ids.add(record.outlet_id)
            records.append(record)

        if batch_cfg.selection_mode == "selected" and not records:
            raise ValueError(
                "mesh_catchment_batch.selected_outlet_ids did not match any outlet row."
            )
        return records

    @staticmethod
    def _load_outlet_rows_from_csv(table_path: Path) -> list[dict[str, Any]]:
        with table_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ValueError(
                    f"mesh_catchment_batch CSV has no header row: {table_path}"
                )
            return [dict(row) for row in reader]

    @staticmethod
    def _load_outlet_rows_from_vector(table_path: Path) -> list[dict[str, Any]]:
        import geopandas as gpd

        gdf = gpd.read_file(table_path)
        if gdf.empty:
            return []
        rows: list[dict[str, Any]] = []
        for _, row in gdf.iterrows():
            payload = {
                str(column): row[column]
                for column in gdf.columns
                if str(column) != "geometry"
            }
            geometry = getattr(row, "geometry", None)
            if geometry is not None and not geometry.is_empty:
                payload.setdefault("geometry_x", float(geometry.x))
                payload.setdefault("geometry_y", float(geometry.y))
            rows.append(payload)
        return rows

    @staticmethod
    def _build_outlet_record(
        *,
        row: Mapping[str, Any],
        outlet_id_column: str,
        x_column: str,
        y_column: str,
        row_label: str,
    ) -> MeshCatchmentOutletRecord:
        if outlet_id_column not in row:
            raise KeyError(f"Missing outlet id column '{outlet_id_column}' in {row_label}")
        outlet_id = _require_text(row.get(outlet_id_column), label=f"{row_label}.{outlet_id_column}")
        try:
            raw_x = row.get(x_column, row.get("geometry_x"))
            raw_y = row.get(y_column, row.get("geometry_y"))
            if raw_x is None or raw_y is None:
                raise KeyError
            x_outlet = float(raw_x)
            y_outlet = float(raw_y)
        except KeyError as exc:
            raise KeyError(
                f"Missing outlet coordinates columns '{x_column}'/'{y_column}' in {row_label}"
            ) from exc
        except Exception as exc:
            raise ValueError(
                f"Invalid outlet coordinates in {row_label}: x={row.get(x_column)!r}, y={row.get(y_column)!r}"
            ) from exc
        return MeshCatchmentOutletRecord(
            outlet_id=outlet_id,
            outlet_id_safe=_sanitize_path_token(outlet_id),
            x_outlet=x_outlet,
            y_outlet=y_outlet,
        )

    def _format_batch_catch_name(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
        record: MeshCatchmentOutletRecord,
    ) -> str:
        tokens = {
            "catch_name": _workspace_catch_name(self.workspace_cfg),
            "outlet_id": record.outlet_id_safe,
        }
        return batch_cfg.catch_name_pattern.format_map(tokens)

    def _resolve_batch_manifest_path(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> Path:
        batch_root = _workspace_project_root(self.workspace_cfg)
        raw_manifest = _optional_text(batch_cfg.outputs.manifest_csv)
        if raw_manifest is None:
            return (batch_root / "mesh_catchment_batch_manifest.csv").resolve()
        manifest_path = Path(raw_manifest).expanduser()
        if manifest_path.is_absolute():
            return manifest_path.resolve()
        return (batch_root / manifest_path).resolve()

    def _build_batch_output_overrides(
        self,
        *,
        workspace_cfg,
        batch_cfg: MeshCatchmentBatchConfig,
        record: MeshCatchmentOutletRecord,
    ) -> dict[str, Path | None]:
        mesh_dir = _workspace_stable_folder(workspace_cfg) / "mesh" / "gmsh"
        catch_name_safe = _sanitize_path_token(_workspace_catch_name(workspace_cfg))
        tokens = {
            "catch_name": catch_name_safe,
            "outlet_id": record.outlet_id_safe,
        }

        def _format_relative(pattern: str | None) -> Path | None:
            if pattern is None:
                return None
            rendered = pattern.format_map(tokens)
            path = Path(rendered).expanduser()
            if path.is_absolute():
                return path.resolve()
            return (mesh_dir / path).resolve()

        return {
            "output_mesh": _format_relative(batch_cfg.outputs.mesh_filename),
            "output_summary_json": _format_relative(batch_cfg.outputs.summary_filename),
            "output_figure": _format_relative(batch_cfg.outputs.figure_filename),
        }

    @staticmethod
    def _write_batch_manifest(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "outlet_id",
            "catch_name",
            "status",
            "x_outlet",
            "y_outlet",
            "output_mesh",
            "output_summary_json",
            "output_figure",
            "error",
        ]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _run_batch(self, batch_cfg: MeshCatchmentBatchConfig) -> dict[str, Any]:
        records = self._load_outlet_records(batch_cfg)
        manifest_path = self._resolve_batch_manifest_path(batch_cfg)
        results: list[dict[str, Any]] = []
        base_catch_name = _workspace_catch_name(self.workspace_cfg)
        base_project_root = _workspace_project_root(self.workspace_cfg)
        base_output_root = getattr(self.workspace_cfg, "output_root", None)

        for record in records:
            catch_name = self._format_batch_catch_name(batch_cfg, record)
            workspace_updates: dict[str, Any] = {
                "project_root": _derive_child_workspace_path(
                    current_path=base_project_root,
                    current_name=base_catch_name,
                    child_name=catch_name,
                ),
            }
            if base_output_root is not None:
                workspace_updates["output_root"] = _derive_child_workspace_path(
                    current_path=Path(base_output_root),
                    current_name=base_catch_name,
                    child_name=catch_name,
                )
            workspace_cfg = _clone_config(
                self.workspace_cfg,
                updates=workspace_updates,
            )
            geographic_cfg = _clone_config(
                self.geographic_cfg,
                updates={
                    "x_outlet": record.x_outlet,
                    "y_outlet": record.y_outlet,
                },
            )
            output_overrides = self._build_batch_output_overrides(
                workspace_cfg=workspace_cfg,
                batch_cfg=batch_cfg,
                record=record,
            )

            try:
                summary = self._run_single_workflow(
                    workspace_cfg=workspace_cfg,
                    geographic_cfg=geographic_cfg,
                    output_overrides=output_overrides,
                )
                results.append(
                    {
                        "outlet_id": record.outlet_id,
                        "catch_name": catch_name,
                        "status": "ok",
                        "x_outlet": record.x_outlet,
                        "y_outlet": record.y_outlet,
                        "output_mesh": summary.get("output_mesh", ""),
                        "output_summary_json": summary.get("output_summary_json", ""),
                        "output_figure": summary.get("output_figure", ""),
                        "error": "",
                    }
                )
                self._write_batch_manifest(manifest_path, results)
            except Exception as exc:
                failure = {
                    "outlet_id": record.outlet_id,
                    "catch_name": catch_name,
                    "status": "error",
                    "x_outlet": record.x_outlet,
                    "y_outlet": record.y_outlet,
                    "output_mesh": "",
                    "output_summary_json": "",
                    "output_figure": "",
                    "error": str(exc),
                }
                results.append(failure)
                self._write_batch_manifest(manifest_path, results)
                if not batch_cfg.continue_on_error:
                    raise

        self._write_batch_manifest(manifest_path, results)
        succeeded = [row for row in results if row["status"] == "ok"]
        failed = [row for row in results if row["status"] != "ok"]
        return {
            "mode": "batch",
            "summary_schema_version": "mesh_catchment_batch_v1",
            "manifest_csv": str(manifest_path),
            "outlets_total": int(len(results)),
            "outlets_succeeded": int(len(succeeded)),
            "outlets_failed": int(len(failed)),
            "results": results,
        }

    def run(self) -> dict[str, Any]:
        """Execute the mesh-only launcher and return the generated summary."""
        if self.batch_cfg is not None:
            return self._run_batch(self.batch_cfg)
        return self._run_single_workflow(
            workspace_cfg=self.workspace_cfg,
            geographic_cfg=self.geographic_cfg,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the mesh-catchment launcher with a TOML config.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / DEFAULT_CONFIG_NAME,
        help=f"Path to launcher TOML file (default: {DEFAULT_CONFIG_NAME}).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run mesh-catchment launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    summary = MeshCatchmentLauncher(args.config.expanduser().resolve()).run()
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
