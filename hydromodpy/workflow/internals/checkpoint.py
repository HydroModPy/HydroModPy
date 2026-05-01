"""Checkpoint serialization for pipeline state.

State is persisted between steps at
``<workspace>/.hmp/checkpoints/<run_id>/<step_index>_<step_name>.pkl.zst``.
Compression uses zstandard when available; otherwise the fallback is
plain pickle (``.pkl``) so the pipeline remains usable without the
optional dependency.

Pickle blobs are HMAC-SHA256 signed with a per-workspace key stored at
``<workspace>/.hmp/checkpoints/.signing_key``. ``restore`` rejects any
blob whose tag does not verify before invoking :func:`pickle.loads`,
which makes the on-disk checkpoints safe against tampering.
"""

from __future__ import annotations

import pickle
import re
from collections.abc import Mapping
from copy import copy
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from hydromodpy.core.io.signed_pickle import (
    dumps_signed,
    load_or_create_key,
    loads_signed,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState, UnpicklableMarker

logger = get_logger(__name__)


try:
    import zstandard as _zstd

    _HAS_ZSTD = True
except ImportError:  # pragma: no cover - optional dep
    _zstd = None
    _HAS_ZSTD = False


_FILENAME_RE = re.compile(r"^(?P<idx>\d+)_(?P<name>.+)\.pkl(?:\.zst)?$")
_KEY_FILENAME = ".signing_key"


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "step"


class CheckpointStore:
    """Persist and restore :class:`PipelineState` snapshots on disk."""

    def __init__(self, workspace: Path, run_id: str) -> None:
        self.workspace = Path(workspace)
        self.run_id = run_id
        self.dir = self.workspace / ".hmp" / "checkpoints" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self.workspace / ".hmp" / "checkpoints" / _KEY_FILENAME

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self, state: PipelineState) -> Path:
        """Write ``state`` to disk and return the written path."""
        stripped = _strip_unpicklable(state)
        key = load_or_create_key(self._key_path)
        blob = dumps_signed(stripped, key)
        path = self._path_for(state.step_index, state.step_name)
        tmp = path.with_name(path.name + ".tmp")
        if _HAS_ZSTD:
            cctx = _zstd.ZstdCompressor(level=3)
            tmp.write_bytes(cctx.compress(blob))
        else:
            tmp.write_bytes(blob)
        tmp.replace(path)
        return path

    def restore(self, step_index: int) -> PipelineState:
        """Load the state saved at the end of step ``step_index``.

        The on-disk blob is HMAC-verified before :func:`pickle.loads` runs,
        so a tampered checkpoint raises rather than executing arbitrary
        code.
        """
        path = self._find_path(step_index)
        if path is None:
            raise FileNotFoundError(f"no checkpoint for step {step_index} in {self.dir}")
        raw = path.read_bytes()
        if path.suffix == ".zst" and _HAS_ZSTD:
            dctx = _zstd.ZstdDecompressor()
            raw = dctx.decompress(raw)
        key = load_or_create_key(self._key_path)
        return loads_signed(raw, key)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def completed_indices(self) -> list[int]:
        """Return the sorted list of step indices that have a checkpoint."""
        indices: list[int] = []
        for p in self.dir.iterdir():
            m = _FILENAME_RE.match(p.name)
            if m is not None:
                indices.append(int(m.group("idx")))
        return sorted(indices)

    def latest(self) -> int | None:
        indices = self.completed_indices()
        return indices[-1] if indices else None

    def latest_before(self, step_index: int) -> int | None:
        """Return the highest completed index strictly below ``step_index``."""
        prior = [i for i in self.completed_indices() if i < step_index]
        return prior[-1] if prior else None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path_for(self, step_index: int, step_name: str) -> Path:
        ext = ".pkl.zst" if _HAS_ZSTD else ".pkl"
        filename = f"{int(step_index):02d}_{_sanitize_name(step_name)}{ext}"
        return self.dir / filename

    def _find_path(self, step_index: int) -> Path | None:
        prefix = f"{int(step_index):02d}_"
        for p in self.dir.iterdir():
            if p.name.startswith(prefix) and p.name.endswith((".pkl", ".pkl.zst")):
                return p
        return None


def _strip_unpicklable(state: PipelineState) -> PipelineState:
    """Return ``state`` with non-picklable ``data`` entries replaced by markers.

    Entries whose value cannot be pickled are replaced by an
    :class:`UnpicklableMarker` carrying the original type name. This lets
    pipelines that carry live resources (DuckDB connections, Zarr groups,
    …) still checkpoint the serializable parts of their state. The markers
    are restored to live objects on resume by :func:`_rebind_unpicklables`.
    """
    if not isinstance(state.data, Mapping):
        return state
    cleaned: dict[str, Any] = {}
    for key, value in state.data.items():
        if _looks_like_workflow_context(value):
            value = _strip_workflow_context(value)
        try:
            pickle.dumps(value)
        except Exception:
            cleaned[key] = UnpicklableMarker(type_name=type(value).__name__)
        else:
            cleaned[key] = value
    return replace(state, data=cleaned)


def _rebind_unpicklables(state: PipelineState, workspace: Path | None) -> PipelineState:
    """Replace :class:`UnpicklableMarker` entries with live rebuilt objects.

    For each ``data[key]`` that is a marker, looks up the factory registered
    on :class:`PipelineState` and calls ``factory(workspace, state)``. Keys
    without a registered factory keep their marker so a downstream step
    that needs the value fails loudly instead of crashing on ``None``.
    """
    if not isinstance(state.data, Mapping):
        return state
    rebound: dict[str, Any] = dict(state.data)
    for key, value in state.data.items():
        if _looks_like_workflow_context(value):
            rebound[key] = _rebind_workflow_context(value, workspace)
            continue
        if not isinstance(value, UnpicklableMarker):
            continue
        factory = PipelineState.get_rebuild_factory(key)
        if factory is None:
            continue
        rebound[key] = factory(workspace, state)
    return replace(state, data=rebound)


def _looks_like_workflow_context(value: Any) -> bool:
    return all(hasattr(value, name) for name in ("cfg", "setup", "execution"))


def _strip_workflow_context(ctx: Any) -> Any:
    """Return a context clone without live catalog or postprocess handles."""
    clone = copy(ctx)
    clone.store = None
    clone.postprocess_runner = None
    clone.setup = _strip_dataclass_fields(ctx.setup)
    clone.loaded_data = _strip_dataclass_fields(ctx.loaded_data)
    clone.execution = _strip_execution_registry(ctx.execution)
    return clone


def _strip_execution_registry(execution: Any) -> Any:
    clone = _strip_dataclass_fields(execution)
    models = getattr(execution, "models_by_run_id", None)
    if isinstance(models, Mapping):
        clone.models_by_run_id = {
            str(key): value
            if _is_picklable(value)
            else UnpicklableMarker(type_name=type(value).__name__)
            for key, value in models.items()
        }
    return clone


def _strip_dataclass_fields(value: Any) -> Any:
    if not is_dataclass(value):
        return value
    clone = copy(value)
    for field in fields(value):
        item = getattr(value, field.name)
        if _is_picklable(item):
            continue
        if isinstance(item, Mapping):
            setattr(
                clone,
                field.name,
                {
                    key: sub
                    if _is_picklable(sub)
                    else UnpicklableMarker(type_name=type(sub).__name__)
                    for key, sub in item.items()
                },
            )
        else:
            setattr(clone, field.name, UnpicklableMarker(type_name=type(item).__name__))
    return clone


def _is_picklable(value: Any) -> bool:
    try:
        pickle.dumps(value)
    except Exception:
        return False
    return True


def _rebind_workflow_context(ctx: Any, workspace: Path | None) -> Any:
    """Reopen live resources stripped from a checkpointed workflow context."""
    if getattr(ctx, "store", None) is not None:
        return ctx
    sim_id = getattr(ctx, "sim_id", None)
    if sim_id in (None, ""):
        return ctx
    persistence = _context_persistence(ctx)
    if persistence is not None and not getattr(persistence, "save_catalog", True):
        return ctx
    workspace_root = _context_workspace_root(ctx, workspace)
    if workspace_root is None:
        return ctx
    from hydromodpy.results.catalog import SimulationCatalog

    ctx.store = SimulationCatalog(workspace_root, persistence=persistence)
    return ctx


def _context_persistence(ctx: Any) -> Any:
    effective = getattr(ctx, "effective_results_config", None)
    if effective is not None:
        return getattr(effective, "persistence", None)
    cfg = getattr(ctx, "cfg", None)
    simulation = getattr(cfg, "simulation", None)
    results = getattr(simulation, "results", None)
    return getattr(results, "persistence", None)


def _context_workspace_root(ctx: Any, workspace: Path | None) -> Path | None:
    setup = getattr(ctx, "setup", None)
    runtime_workspace = getattr(setup, "workspace", None) if setup is not None else None
    root = getattr(runtime_workspace, "root", None)
    if root is not None:
        return Path(root)
    return Path(workspace) if workspace is not None else None


__all__ = ("CheckpointStore",)
