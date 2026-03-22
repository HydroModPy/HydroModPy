"""Dedicated launcher for catchment meshing workflows.

This module is the user-facing entry point of the mesh-only workflow. It does
not generate meshes by itself; instead it performs the orchestration work that
turns one launcher TOML into the concrete runtime objects consumed by the
geographic preprocessing pipeline and by the 2D conformal meshing case.

The main responsibilities here are:

- load and validate the launcher-specific sections;
- load the shared runtime sections (`workspace`, `geographic`, optional
  `domain`);
- derive safe defaults that are convenient for dedicated meshing runs;
- expand optional batch mode into one sequence of child mono-catchment runs;
- keep per-outlet outputs isolated and track progress in a manifest.

Two usage patterns are supported:

- single-run mode: one outlet / one catchment / one final mesh summary;
- batch mode: one outlets table is iterated and each outlet gets its own child
  workspace, derived geographic inputs, output filenames, and one manifest row.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import rasterio
import sys
from types import SimpleNamespace
from typing import Any

# When this file is executed directly by path, Python adds the script folder to
# ``sys.path`` but not necessarily the repository root. Insert the repo root
# explicitly so local imports always resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hydromodpy.config.hydromodpy_config import _load_standard_section
from hydromodpy.config.toml_loader import load_toml_with_base_config
from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig
from launchers.mesh_catchment import runtime as mesh_runtime
from launchers.mesh_catchment.config import parse_mesh_catchment_batch_config_data


DEFAULT_CONFIG_NAME = "config_example.toml"
_VECTOR_TABLE_SUFFIXES = {".geojson", ".gpkg", ".json", ".shp"}


# ---------------------------------------------------------------------------
# Lightweight launcher-only data carriers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MeshCatchmentBatchOutputsConfig:
    """Resolved filename patterns used to materialize one outlet batch run.

    The launcher normalizes these patterns once, then formats them per outlet
    with tokens such as ``{outlet_id}`` and ``{catch_name}``. Keeping this
    small dataclass separate from the larger batch config makes it easier to
    reason about which values are true runtime paths versus user-authored
    pattern strings.
    """
    mesh_filename: str | None = None
    summary_filename: str | None = None
    figure_filename: str | None = None
    figure_regional_filename: str | None = None
    manifest_csv: str | None = None


@dataclass(frozen=True)
class MeshCatchmentBatchConfig:
    """Normalized batch-loop contract derived from `[mesh_catchment_batch]`.

    By the time an instance of this class exists, the launcher has already
    resolved relative paths, normalized selection lists, and checked the core
    structural rules of batch mode. Downstream code can therefore iterate over
    outlets without having to repeatedly defend against half-parsed TOML values.
    """
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
        """Parse the optional batch section and return ``None`` when disabled."""
        if raw_value is None:
            return None
        validated = parse_mesh_catchment_batch_config_data(raw_value)
        if not validated.enabled:
            return None

        outlets_table_path = _resolve_required_path(
            validated.outlets_table_path,
            label="mesh_catchment_batch.outlets_table_path",
            base_dir=base_dir,
        )
        outlet_id_column = _require_text(
            validated.outlet_id_column,
            label="mesh_catchment_batch.outlet_id_column",
        )
        x_column = _require_text(
            validated.x_column,
            label="mesh_catchment_batch.x_column",
        )
        y_column = _require_text(
            validated.y_column,
            label="mesh_catchment_batch.y_column",
        )

        selection_mode = validated.selection_mode
        selected_outlet_ids = tuple(validated.selected_outlet_ids)

        catch_name_pattern = _require_text(
            validated.catch_name_pattern,
            label="mesh_catchment_batch.catch_name_pattern",
        )
        outputs_cfg = validated.outputs
        outputs = MeshCatchmentBatchOutputsConfig(
            mesh_filename=outputs_cfg.mesh_filename,
            summary_filename=outputs_cfg.summary_filename,
            figure_filename=outputs_cfg.figure_filename,
            figure_regional_filename=outputs_cfg.figure_regional_filename,
            manifest_csv=outputs_cfg.manifest_csv,
        )

        return cls(
            outlets_table_path=outlets_table_path,
            outlet_id_column=outlet_id_column,
            x_column=x_column,
            y_column=y_column,
            selection_mode=selection_mode,
            selected_outlet_ids=selected_outlet_ids,
            catch_name_pattern=catch_name_pattern,
            continue_on_error=validated.continue_on_error,
            outputs=outputs,
        )


@dataclass(frozen=True)
class MeshCatchmentOutletRecord:
    """One normalized outlet row ready to drive a child catchment run."""
    outlet_id: str
    outlet_id_safe: str
    x_outlet: float
    y_outlet: float


def _optional_text(raw_value: object) -> str | None:
    """Return one stripped string, or ``None`` for null/empty values."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _require_text(raw_value: object, *, label: str) -> str:
    """Return one non-empty string and raise a contextual error otherwise."""
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
    """Resolve one required file path relative to the launcher TOML directory."""
    text = _require_text(raw_value, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _sanitize_path_token(raw_value: object) -> str:
    """Convert one user-facing token into a filesystem-safe path fragment."""
    text = str(raw_value).strip()
    if text == "":
        return "unknown"
    collapsed = re.sub(r"\s+", "_", text)
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = sanitized.strip("._-")
    return sanitized or "unknown"


def _clone_config(config: object, *, updates: Mapping[str, Any]) -> object:
    """Clone one config-like object while preserving Pydantic validation when possible."""
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
    """Return the catchment name represented by one workspace-like object."""
    return str(Path(workspace_like.project_root).name)


def _workspace_project_root(workspace_like: object) -> Path:
    """Return the project root path for one workspace-like object."""
    return Path(workspace_like.project_root)


def _workspace_output_root(workspace_like: object) -> Path:
    """Return the explicit output root, or fall back to the project root."""
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
    """Derive one child workspace path while preserving parent folder layout."""
    if current_path.name == str(current_name):
        return current_path.parent / child_name
    return current_path / child_name


def _workspace_stable_folder(workspace_like: object) -> Path:
    """Return the canonical `results_stable` folder for one workspace-like object."""
    stable_folder = getattr(workspace_like, "stable_folder", None)
    if stable_folder is not None:
        return Path(stable_folder)
    output_root = getattr(workspace_like, "output_root", None)
    if output_root is not None:
        return Path(output_root) / "results_stable"
    return Path(workspace_like.project_root) / "results_stable"


def _point_is_within_bounds(*, x: float, y: float, bounds) -> bool:
    """Return whether one projected XY point lies inside raster bounds."""
    return (
        float(bounds.left) <= float(x) <= float(bounds.right)
        and float(bounds.bottom) <= float(y) <= float(bounds.top)
    )


class MeshCatchmentLauncher:
    """Run one mesh-only workflow from the ``[mesh_catchment]`` TOML section."""

    SECTION_NAME = "mesh_catchment"

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.raw_toml = load_toml_with_base_config(self.config_path)
        self.mesh_section_data = mesh_runtime.require_mesh_section(self.raw_toml)
        # The launcher has its own TOML section, but it still depends on the
        # shared workspace/geographic/domain runtime sections to do actual work.
        self.workspace_cfg, self.geographic_cfg, self.domain_cfg = self._load_runtime_configs(
            self.raw_toml
        )
        self.constraints_mode = self.mesh_section_data.constraints_mode
        # River-constrained meshing requires the geographic pipeline to produce
        # a river trace, so we upgrade the geographic config here if needed.
        self.geographic_cfg = mesh_runtime.prepare_geographic_config_for_meshing(
            self.geographic_cfg,
            constraints_mode=self.constraints_mode,
            section_name=self.SECTION_NAME,
        )
        self.batch_cfg = MeshCatchmentBatchConfig.from_mapping(
            self.raw_toml.get("mesh_catchment_batch"),
            base_dir=self.config_path.parent,
        )
        if self.batch_cfg is not None:
            self._validate_batch_output_configuration(self.batch_cfg)
            self._validate_batch_raster_coverage(self.batch_cfg)

    def _normalize_workspace_section(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return one workspace payload with launcher-friendly defaults applied.

        The dedicated meshing launcher is intentionally easy to bootstrap for
        local experiments. When the TOML omits ``workspace.project_root`` we do
        not fail immediately: we fall back to the config directory so the rest
        of the shared workspace loader still receives a concrete location.
        """
        base_dir = self.config_path.parent
        workspace_data = dict(payload.get("workspace", {}))

        if not workspace_data.get("project_root"):
            workspace_data["project_root"] = str(base_dir)

        return workspace_data

    def _load_runtime_configs(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[WorkspaceConfig, GeographicConfig, DomainConfig]:
        """Load the shared runtime sections consumed by the launcher.

        Even though this launcher is centered on ``[mesh_catchment]``, the real
        workflow still depends on the common HydroModPy runtime contracts:

        - ``workspace`` controls where derived artifacts are written;
        - ``geographic`` controls catchment delineation and optional river
          tracing;
        - ``domain`` optionally provides vertical information used later by the
          exchange-bundle export.

        This method keeps that bridge explicit so the launcher remains a thin
        adapter rather than a parallel configuration system.
        """
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
        # The vertical model may feed mesh-bundle export, so the launcher loads
        # `[domain]` when present instead of ignoring it.
        if "domain" in payload:
            domain_cfg = _load_standard_section(
                payload.get("domain", {}),
                DomainConfig,
                base_dir,
            )
        else:
            domain_cfg = DomainConfig()
        return workspace_cfg, geographic_cfg, domain_cfg

    def _run_single_workflow(
        self,
        *,
        workspace_cfg,
        geographic_cfg,
        domain_cfg,
        output_overrides: Mapping[str, Path | None] | None = None,
    ) -> dict[str, Any]:
        """Delegate one fully prepared mono-catchment run to the shared runtime layer."""
        return mesh_runtime.run_single_mesh_catchment_workflow(
            config_path=self.config_path,
            section_data=self.mesh_section_data,
            workspace_cfg=workspace_cfg,
            geographic_cfg=geographic_cfg,
            domain_cfg=domain_cfg,
            constraints_mode=self.constraints_mode,
            output_overrides=output_overrides,
            section_name=self.SECTION_NAME,
        )

    def _validate_batch_output_configuration(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> None:
        """Reject batch runs that would overwrite fixed output paths.

        Batch mode reuses the same launcher section for many outlets. A fixed
        ``mesh_catchment.output_*`` path would therefore point every outlet to
        the same filename unless a per-outlet pattern is configured in
        ``mesh_catchment_batch.outputs``. Failing early here is clearer than
        letting the last outlet silently overwrite previous results.
        """
        required_patterns = {
            "output_mesh": "mesh_filename",
            "output_summary_json": "summary_filename",
            "output_figure": "figure_filename",
            "output_figure_regional": "figure_regional_filename",
        }
        for section_key, pattern_attr in required_patterns.items():
            raw_value = getattr(self.mesh_section_data, section_key)
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

    def _validate_batch_raster_coverage(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> None:
        """Fail fast when selected batch outlets fall outside required raster coverage."""
        records = self._load_outlet_records(batch_cfg)
        if not records:
            return

        # The DEM must cover every outlet because delineation starts from that
        # point. Catch this upfront instead of failing later inside Whitebox.
        dem_path = Path(self.geographic_cfg.dem_init_path).expanduser().resolve()
        self._validate_outlets_within_raster(
            records=records,
            raster_path=dem_path,
            label="geographic.dem_init_path",
        )

        geology_cfg = self.mesh_section_data.geology
        if geology_cfg is None:
            return
        reference_raster_raw = _optional_text(geology_cfg.source.reference_raster_path)
        if reference_raster_raw is None:
            return
        reference_raster_path = Path(reference_raster_raw).expanduser()
        if not reference_raster_path.is_absolute():
            reference_raster_path = (self.config_path.parent / reference_raster_path).resolve()
        self._validate_outlets_within_raster(
            records=records,
            raster_path=reference_raster_path,
            label="mesh_catchment.geology.source.reference_raster_path",
        )

    @staticmethod
    def _validate_outlets_within_raster(
        *,
        records: Sequence[MeshCatchmentOutletRecord],
        raster_path: Path,
        label: str,
    ) -> None:
        """Check that all selected outlets lie within one raster extent."""
        if not raster_path.exists():
            raise FileNotFoundError(f"{label} not found: {raster_path}")

        with rasterio.open(raster_path) as src:
            bounds = src.bounds
            outside = [
                record
                for record in records
                if not _point_is_within_bounds(
                    x=record.x_outlet,
                    y=record.y_outlet,
                    bounds=bounds,
                )
            ]

        if not outside:
            return

        sample = ", ".join(
            f"{record.outlet_id}({record.x_outlet:.3f},{record.y_outlet:.3f})"
            for record in outside[:3]
        )
        raise ValueError(
            f"{label} does not cover all selected batch outlets. "
            f"Raster bounds are {bounds}. First outside outlet(s): {sample}. "
            "Override the batch config with a DEM/reference raster that covers the full outlets table."
        )

    def _load_outlet_records(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> list[MeshCatchmentOutletRecord]:
        """Load and normalize outlet rows from the configured batch table.

        This method is the boundary between loose user input and the typed
        outlet records used by the rest of the batch pipeline. It accepts CSV
        or vector formats, applies the optional outlet selection mode, and
        rejects ambiguous situations such as duplicated outlet ids before any
        expensive geographic or meshing work starts.
        """
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
            # Normalize each input row once so the rest of the batch pipeline
            # only manipulates typed outlet records.
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
        """Read outlet rows from one CSV file with a header row."""
        with table_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ValueError(
                    f"mesh_catchment_batch CSV has no header row: {table_path}"
                )
            return [dict(row) for row in reader]

    @staticmethod
    def _load_outlet_rows_from_vector(table_path: Path) -> list[dict[str, Any]]:
        """Read outlet rows from one vector file and expose point XY columns."""
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
        """Validate one raw table row and convert it into one outlet record."""
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
        """Render the child catchment name for one outlet record."""
        tokens = {
            "catch_name": _workspace_catch_name(self.workspace_cfg),
            "outlet_id": record.outlet_id_safe,
        }
        return batch_cfg.catch_name_pattern.format_map(tokens)

    def _resolve_batch_manifest_path(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> Path:
        """Return the manifest CSV path used to track batch progress."""
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
        """Build outlet-specific output overrides for one child run.

        Batch mode derives final filenames outside the generic meshing case so
        the dedicated launcher keeps full control over naming conventions. The
        exact parent folder depends on the output layout:

        - ``standard`` writes under ``results_stable/mesh`` of the child
          workspace;
        - ``flat`` writes directly under the child project root.
        """
        output_layout = mesh_runtime.resolve_output_layout(self.mesh_section_data)
        mesh_dir = (
            _workspace_project_root(workspace_cfg)
            if output_layout == "flat"
            else _workspace_stable_folder(workspace_cfg) / "mesh"
        )
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
            "output_figure_regional": _format_relative(
                batch_cfg.outputs.figure_regional_filename
            ),
        }

    def _build_batch_child_runtime(
        self,
        *,
        batch_cfg: MeshCatchmentBatchConfig,
        record: MeshCatchmentOutletRecord,
    ) -> tuple[str, object, object, dict[str, Path | None]]:
        """Derive child workspace/geographic configs for one outlet run.

        The parent launcher config acts as a template. For each outlet we clone
        that template into a child runtime view with:

        - a dedicated workspace root so intermediate geographic products stay
          isolated;
        - outlet-specific ``x_outlet`` / ``y_outlet`` coordinates;
        - outlet-specific final output filenames.

        This keeps each outlet effectively equivalent to an independent
        mono-catchment run, while still letting the batch loop reuse shared
        configuration and reporting logic.
        """
        base_catch_name = _workspace_catch_name(self.workspace_cfg)
        base_project_root = _workspace_project_root(self.workspace_cfg)
        base_output_root = getattr(self.workspace_cfg, "output_root", None)

        catch_name = self._format_batch_catch_name(batch_cfg, record)
        # Each outlet gets its own workspace subtree so geographic
        # preprocessing, mesh outputs, and cleanup remain isolated.
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
        return catch_name, workspace_cfg, geographic_cfg, output_overrides

    @staticmethod
    def _build_batch_result_row(
        *,
        record: MeshCatchmentOutletRecord,
        catch_name: str,
        status: str,
        summary: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        """Build one manifest row summarizing the outcome of a batch child run."""
        summary = dict(summary or {})
        return {
            "outlet_id": record.outlet_id,
            "catch_name": catch_name,
            "status": status,
            "x_outlet": record.x_outlet,
            "y_outlet": record.y_outlet,
            "output_mesh": summary.get("output_mesh", ""),
            "output_summary_json": summary.get("output_summary_json", ""),
            "output_figure": summary.get("output_figure", ""),
            "output_figure_regional": summary.get("output_figure_regional", ""),
            "error": error,
        }

    @staticmethod
    def _write_batch_manifest(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        """Persist the current batch progress to one CSV manifest."""
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
            "output_figure_regional",
            "error",
        ]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _run_batch(self, batch_cfg: MeshCatchmentBatchConfig) -> dict[str, Any]:
        """Run the outlet loop and keep a manifest updated incrementally.

        The manifest is written after every outlet, both on success and on
        failure. This is deliberate: batch meshing can be long, and users need
        to inspect partial progress without waiting for the entire table to
        finish. The final summary returned by this method is therefore both a
        machine-readable result payload and a compact recap of the manifest.
        """
        records = self._load_outlet_records(batch_cfg)
        manifest_path = self._resolve_batch_manifest_path(batch_cfg)
        results: list[dict[str, Any]] = []

        for record in records:
            catch_name, workspace_cfg, geographic_cfg, output_overrides = (
                self._build_batch_child_runtime(
                    batch_cfg=batch_cfg,
                    record=record,
                )
            )

            try:
                # Each outlet is executed as a normal single workflow with its
                # own derived workspace/config view. Persist the manifest right
                # away so the batch remains observable while it is still
                # running.
                summary = self._run_single_workflow(
                    workspace_cfg=workspace_cfg,
                    geographic_cfg=geographic_cfg,
                    domain_cfg=self.domain_cfg,
                    output_overrides=output_overrides,
                )
                results.append(
                    self._build_batch_result_row(
                        record=record,
                        catch_name=catch_name,
                        status="ok",
                        summary=summary,
                    )
                )
                self._write_batch_manifest(manifest_path, results)
            except Exception as exc:
                # Mirror the same incremental manifest update on failures. That
                # way a partially failed batch still leaves an explicit trail
                # describing which outlets succeeded, which failed, and why.
                results.append(
                    self._build_batch_result_row(
                        record=record,
                        catch_name=catch_name,
                        status="error",
                        error=str(exc),
                    )
                )
                self._write_batch_manifest(manifest_path, results)
                if not batch_cfg.continue_on_error:
                    # In strict mode the first failing outlet aborts the loop
                    # after the manifest has been updated, so users do not lose
                    # the failure context.
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
        """Execute the launcher and return the final summary payload.

        In single mode the returned payload is the mono-catchment meshing
        summary produced by the runtime layer. In batch mode the returned
        payload is a launcher-level summary that aggregates per-outlet rows and
        points to the generated manifest CSV.
        """
        if self.batch_cfg is not None:
            return self._run_batch(self.batch_cfg)
        return self._run_single_workflow(
            workspace_cfg=self.workspace_cfg,
            geographic_cfg=self.geographic_cfg,
            domain_cfg=self.domain_cfg,
        )


def _build_parser() -> argparse.ArgumentParser:
    """Build the small CLI parser used when launching this module directly."""
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
    """Run the mesh-catchment launcher with a provided TOML or default local config."""
    args = _build_parser().parse_args(argv)
    summary = MeshCatchmentLauncher(args.config.expanduser().resolve()).run()
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
