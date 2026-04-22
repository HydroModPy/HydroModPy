"""Checkpoint serialization for pipeline state.

State is persisted between steps at
``<workspace>/.hmp/checkpoints/<run_id>/<step_index>_<step_name>.pkl.zst``.
Compression uses zstandard when available; otherwise the fallback is
plain pickle (``.pkl``) so the pipeline remains usable without the
optional dependency.
"""

from __future__ import annotations

import logging
import pickle
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from hydromodpy.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


try:
    import zstandard as _zstd
    _HAS_ZSTD = True
except ImportError:  # pragma: no cover — optional dep
    _zstd = None
    _HAS_ZSTD = False


_FILENAME_RE = re.compile(r"^(?P<idx>\d+)_(?P<name>.+)\.pkl(?:\.zst)?$")


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "step"


class CheckpointStore:
    """Persist and restore :class:`PipelineState` snapshots on disk."""

    def __init__(self, workspace: Path, run_id: str) -> None:
        self.workspace = Path(workspace)
        self.run_id = run_id
        self.dir = self.workspace / ".hmp" / "checkpoints" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self, state: PipelineState) -> Path:
        """Write ``state`` to disk and return the written path."""
        stripped = _strip_unpicklable(state)
        blob = pickle.dumps(stripped, protocol=pickle.HIGHEST_PROTOCOL)
        path = self._path_for(state.step_index, state.step_name)
        if _HAS_ZSTD:
            cctx = _zstd.ZstdCompressor(level=3)
            path.write_bytes(cctx.compress(blob))
        else:
            path.write_bytes(blob)
        return path

    def restore(self, step_index: int) -> PipelineState:
        """Load the state saved at the end of step ``step_index``."""
        path = self._find_path(step_index)
        if path is None:
            raise FileNotFoundError(
                f"no checkpoint for step {step_index} in {self.dir}"
            )
        raw = path.read_bytes()
        if path.suffix == ".zst" and _HAS_ZSTD:
            dctx = _zstd.ZstdDecompressor()
            raw = dctx.decompress(raw)
        return pickle.loads(raw)

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

    Entries whose value cannot be pickled are replaced by a sentinel string
    ``"<unpicklable:<type>>"``. This allows pipelines that carry live
    resources (DuckDB connections, open files, …) to still checkpoint the
    serializable parts of their state.
    """
    cleaned: dict[str, Any] = {}
    for key, value in state.data.items():
        try:
            pickle.dumps(value)
        except Exception:
            cleaned[key] = f"<unpicklable:{type(value).__name__}>"
        else:
            cleaned[key] = value
    return replace(state, data=cleaned)


__all__ = ("CheckpointStore",)
