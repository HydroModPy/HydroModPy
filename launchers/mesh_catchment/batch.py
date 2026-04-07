"""Batch helpers for the dedicated mesh-catchment launcher.

This module owns the multi-outlet workflow built on top of the dedicated
``[mesh_catchment_batch]`` contract. The main launcher stays responsible for
bootstrap work only: loading the shared runtime sections, preparing the mesh
section, and delegating either to one mono-catchment run or to this batch
layer.

The supporting pieces are intentionally split by concern:

* ``batch_io`` reads and validates outlet tables plus raster coverage.
* ``batch_reporting`` persists manifest rows and the final batch summary.
* this module keeps only the orchestration of child runs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

logger = logging.getLogger(__name__)

from launchers.mesh_catchment.batch_io import (
    MeshCatchmentOutletRecord,
    load_mesh_catchment_outlet_records,
    sanitize_batch_path_token,
    validate_outlets_within_raster,
)
from launchers.mesh_catchment.batch_reporting import (
    MeshCatchmentBatchResultRow,
    MeshCatchmentBatchSummary,
    write_mesh_catchment_batch_manifest,
)
from launchers.mesh_catchment.config import (
    MeshCatchmentConfigSchema,
    parse_mesh_catchment_batch_config_data,
)
from launchers.mesh_catchment.runtime_single_run import clone_config_like


class _RecordedBatchFailure(RuntimeError):
    """Internal marker used when one batch failure has already been recorded."""


@dataclass(frozen=True)
class MeshCatchmentBatchOutputsConfig:
    """Resolved filename patterns used to materialize one outlet batch run."""

    mesh_filename: str | None = None
    summary_filename: str | None = None
    figure_filename: str | None = None
    figure_regional_filename: str | None = None
    manifest_csv: str | None = None


@dataclass(frozen=True)
class MeshCatchmentBatchConfig:
    """Normalized batch-loop contract derived from ``[mesh_catchment_batch]``."""

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
        catch_name_pattern = _require_text(
            validated.catch_name_pattern,
            label="mesh_catchment_batch.catch_name_pattern",
        )
        outputs = MeshCatchmentBatchOutputsConfig(
            mesh_filename=validated.outputs.mesh_filename,
            summary_filename=validated.outputs.summary_filename,
            figure_filename=validated.outputs.figure_filename,
            figure_regional_filename=validated.outputs.figure_regional_filename,
            manifest_csv=validated.outputs.manifest_csv,
        )

        return cls(
            outlets_table_path=outlets_table_path,
            outlet_id_column=outlet_id_column,
            x_column=x_column,
            y_column=y_column,
            selection_mode=validated.selection_mode,
            selected_outlet_ids=tuple(validated.selected_outlet_ids),
            catch_name_pattern=catch_name_pattern,
            continue_on_error=validated.continue_on_error,
            outputs=outputs,
        )


@dataclass(frozen=True)
class MeshCatchmentBatchRunner:
    """Orchestrate the multi-outlet mesh workflow for one launcher session."""

    config_path: Path
    mesh_section_data: MeshCatchmentConfigSchema
    workspace_cfg: object
    geographic_cfg: object
    domain_cfg: object | None
    run_single_workflow: Callable[..., dict[str, Any]]

    def validate_output_configuration(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> None:
        """Reject batch runs that would overwrite fixed output paths."""
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

    def validate_raster_coverage(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> None:
        """Fail fast when selected batch outlets fall outside required raster coverage."""
        records = self._load_outlet_records(batch_cfg)
        if not records:
            return

        dem_path = Path(self.geographic_cfg.dem_init_path).expanduser().resolve()
        validate_outlets_within_raster(
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
            reference_raster_path = (
                self.config_path.parent / reference_raster_path
            ).resolve()
        validate_outlets_within_raster(
            records=records,
            raster_path=reference_raster_path,
            label="mesh_catchment.geology.source.reference_raster_path",
        )

    def run(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> dict[str, Any]:
        """Run the outlet loop and keep the manifest updated incrementally."""
        records = self._load_outlet_records(batch_cfg)
        manifest_path = self._resolve_manifest_path(batch_cfg)
        results: list[MeshCatchmentBatchResultRow] = []

        for record in records:
            catch_name, workspace_cfg, geographic_cfg, output_overrides = (
                self._build_child_runtime(
                    batch_cfg=batch_cfg,
                    record=record,
                )
            )

            try:
                summary = self.run_single_workflow(
                    workspace_cfg=workspace_cfg,
                    geographic_cfg=geographic_cfg,
                    domain_cfg=self.domain_cfg,
                    output_overrides=output_overrides,
                )
                failure_message = self._detect_failed_mesh_run(summary)
                if failure_message is not None:
                    self._emit_batch_error(
                        catch_name=catch_name,
                        outlet_id=record.outlet_id,
                        message=failure_message,
                    )
                    results.append(
                        self._build_result_row(
                            record=record,
                            catch_name=catch_name,
                            status="error",
                            summary=summary,
                            error=failure_message,
                        )
                    )
                    write_mesh_catchment_batch_manifest(manifest_path, results)
                    if not batch_cfg.continue_on_error:
                        raise _RecordedBatchFailure(failure_message)
                    continue
                results.append(
                    self._build_result_row(
                        record=record,
                        catch_name=catch_name,
                        status="ok",
                        summary=summary,
                    )
                )
                write_mesh_catchment_batch_manifest(manifest_path, results)
            except _RecordedBatchFailure as exc:
                raise RuntimeError(str(exc)) from None
            except Exception as exc:
                error_message = self._format_batch_exception(exc)
                self._emit_batch_error(
                    catch_name=catch_name,
                    outlet_id=record.outlet_id,
                    message=error_message,
                )
                results.append(
                    self._build_result_row(
                        record=record,
                        catch_name=catch_name,
                        status="error",
                        error=error_message,
                    )
                )
                write_mesh_catchment_batch_manifest(manifest_path, results)
                if not batch_cfg.continue_on_error:
                    raise

        write_mesh_catchment_batch_manifest(manifest_path, results)
        return MeshCatchmentBatchSummary(
            manifest_csv=str(manifest_path),
            results=tuple(results),
        ).to_mapping()

    def _load_outlet_records(
        self,
        batch_cfg: MeshCatchmentBatchConfig,
    ) -> list[MeshCatchmentOutletRecord]:
        """Load and normalize outlet rows from the configured batch table."""
        return load_mesh_catchment_outlet_records(
            table_path=batch_cfg.outlets_table_path,
            selection_mode=batch_cfg.selection_mode,
            selected_outlet_ids=batch_cfg.selected_outlet_ids,
            outlet_id_column=batch_cfg.outlet_id_column,
            x_column=batch_cfg.x_column,
            y_column=batch_cfg.y_column,
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

    def _resolve_manifest_path(
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

    def _build_output_overrides(
        self,
        *,
        workspace_cfg: object,
        batch_cfg: MeshCatchmentBatchConfig,
        record: MeshCatchmentOutletRecord,
    ) -> dict[str, Path | None]:
        """Build outlet-specific output overrides for one child run."""
        output_layout = self.mesh_section_data.output_layout
        mesh_dir = (
            _workspace_project_root(workspace_cfg)
            if output_layout == "flat"
            else _workspace_stable_folder(workspace_cfg) / "mesh"
        )
        catch_name_safe = sanitize_batch_path_token(
            _workspace_catch_name(workspace_cfg)
        )
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

    def _build_child_runtime(
        self,
        *,
        batch_cfg: MeshCatchmentBatchConfig,
        record: MeshCatchmentOutletRecord,
    ) -> tuple[str, object, object, dict[str, Path | None]]:
        """Derive child workspace/geographic configs for one outlet run."""
        base_catch_name = _workspace_catch_name(self.workspace_cfg)
        base_project_root = _workspace_project_root(self.workspace_cfg)
        base_output_root = getattr(self.workspace_cfg, "output_root", None)

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
        workspace_cfg = clone_config_like(
            self.workspace_cfg,
            updates=workspace_updates,
        )
        geographic_cfg = clone_config_like(
            self.geographic_cfg,
            updates={
                "x_outlet": record.x_outlet,
                "y_outlet": record.y_outlet,
            },
        )
        output_overrides = self._build_output_overrides(
            workspace_cfg=workspace_cfg,
            batch_cfg=batch_cfg,
            record=record,
        )
        return catch_name, workspace_cfg, geographic_cfg, output_overrides

    @staticmethod
    def _build_result_row(
        *,
        record: MeshCatchmentOutletRecord,
        catch_name: str,
        status: str,
        summary: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> MeshCatchmentBatchResultRow:
        """Build one manifest row summarizing the outcome of a batch child run."""
        summary_payload = dict(summary or {})
        return MeshCatchmentBatchResultRow(
            outlet_id=record.outlet_id,
            catch_name=catch_name,
            status=status,
            x_outlet=record.x_outlet,
            y_outlet=record.y_outlet,
            output_mesh=_optional_text(summary_payload.get("output_mesh")) or "",
            output_summary_json=(
                _optional_text(summary_payload.get("output_summary_json")) or ""
            ),
            output_figure=_optional_text(summary_payload.get("output_figure")) or "",
            output_figure_regional=(
                _optional_text(summary_payload.get("output_figure_regional")) or ""
            ),
            error=error,
        )

    @staticmethod
    def _format_batch_exception(exc: Exception) -> str:
        """Render one concise batch error message with exception type context."""
        message = str(exc).strip()
        if message == "":
            return exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"

    @staticmethod
    def _emit_batch_error(*, catch_name: str, outlet_id: str, message: str) -> None:
        """Log one short error line while keeping the batch loop alive."""
        logger.error(
            "mesh_catchment batch outlet=%s catch=%s: %s",
            outlet_id,
            catch_name,
            message,
        )

    def _detect_failed_mesh_run(
        self,
        summary: Mapping[str, Any],
    ) -> str | None:
        """Detect one run that returned a summary but did not actually write a mesh."""
        output_mesh_raw = _optional_text(summary.get("output_mesh"))
        if output_mesh_raw is None:
            return (
                "Mesh generation returned a summary but no output mesh path. "
                "The run is treated as failed."
            )
        output_mesh = Path(output_mesh_raw).expanduser()
        if not output_mesh.is_absolute():
            output_mesh = output_mesh.resolve()
        if output_mesh.exists():
            return None
        return (
            "Mesh generation returned a summary but did not write the expected "
            f"mesh file: {output_mesh}"
        )


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


def _workspace_catch_name(workspace_like: object) -> str:
    """Return the catchment name represented by one workspace-like object."""
    return str(Path(workspace_like.project_root).name)


def _workspace_project_root(workspace_like: object) -> Path:
    """Return the project root path for one workspace-like object."""
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
    """Return the canonical ``results_stable`` folder for one workspace-like object."""
    stable_folder = getattr(workspace_like, "stable_folder", None)
    if stable_folder is not None:
        return Path(stable_folder)
    output_root = getattr(workspace_like, "output_root", None)
    if output_root is not None:
        return Path(output_root) / "results_stable"
    return Path(workspace_like.project_root) / "results_stable"


__all__ = [
    "MeshCatchmentBatchConfig",
    "MeshCatchmentBatchOutputsConfig",
    "MeshCatchmentBatchRunner",
    "MeshCatchmentBatchResultRow",
    "MeshCatchmentBatchSummary",
    "MeshCatchmentOutletRecord",
]
