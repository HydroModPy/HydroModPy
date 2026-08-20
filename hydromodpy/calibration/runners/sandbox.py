"""Per-trial solver sandbox for parallel calibration.

Each calibration trial runs an independent, single-threaded solver subprocess.
When the engine evaluates several trials at once (``calibration.parallel > 1``),
those subprocesses must not write to the same model folder or they overwrite
each other's input/output files.

:class:`TrialSandbox` gives one trial a private solver identity: a per-trial
``model_name_override`` so the solver writes into its own ``<scratch>/<model>/``
folder (the shared, read-only preprocessing under ``<scratch>/`` stays shared).
It is a context manager (RAII): on exit it removes the trial's solver output
directories. Set ``HMP_KEEP_TRIAL_SCRATCH=1`` to retain them for debugging.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

KEEP_ENV_VAR = "HMP_KEEP_TRIAL_SCRATCH"

_SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")


def keep_trial_scratch() -> bool:
    """Return True when the environment asks to retain calibration scratch dirs.

    Covers both the per-trial solver folders and the session-wide preprocessing
    tree: a debugging session that keeps one keeps the other.
    """
    value = os.environ.get(KEEP_ENV_VAR)
    return value is not None and value.strip().lower() not in ("", "0", "false", "no")


def _sanitize(name: str) -> str:
    """Return a filesystem-safe model-name stem."""
    cleaned = _SAFE_NAME.sub("-", str(name).strip()) or "trial"
    return cleaned


class TrialSandbox:
    """Isolated solver identity for one calibration trial.

    Parameters
    ----------
    base_model_name
        The session's base model name (usually ``setup.run_id``). The trial
        model name is derived from it so a retained folder is easy to locate.
    trial_id
        Unique trial identifier.
    keep
        Retain the trial's solver output on exit. Defaults to the
        ``HMP_KEEP_TRIAL_SCRATCH`` environment variable.
    """

    def __init__(
        self,
        base_model_name: str,
        trial_id: int,
        *,
        keep: bool | None = None,
        solver_scratch_folder: Path | str | None = None,
    ) -> None:
        self.model_name = f"{_sanitize(base_model_name)}_trial{int(trial_id):06d}"
        self._keep = keep_trial_scratch() if keep is None else bool(keep)
        self._execution: Any | None = None
        # Eager output dir: the trial writes into <scratch>/<model_name>/, so a
        # diverged / timed-out / crashed trial (which never records a success in
        # the run registry) is still cleaned up on exit.
        self._eager_dir: Path | None = (
            Path(solver_scratch_folder) / self.model_name if solver_scratch_folder else None
        )

    @property
    def flow_overrides(self) -> dict[str, str]:
        """Flow runtime overrides that pin this trial to its own model folder."""
        return {"model_name_override": self.model_name}

    def track(self, execution: Any) -> None:
        """Record the forked execution registry whose outputs to clean up."""
        self._execution = execution

    def _output_dirs(self) -> list[Path]:
        registry = getattr(self._execution, "output_dirs_by_run_id", None) or {}
        candidates = [Path(p) for p in registry.values() if p]
        if self._eager_dir is not None:
            candidates.append(self._eager_dir)
        seen: set[str] = set()
        unique: list[Path] = []
        for path in candidates:
            key = str(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def __enter__(self) -> TrialSandbox:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._keep:
            for path in self._output_dirs():
                logger.debug("Kept trial output %s (%s set)", path, KEEP_ENV_VAR)
            return False
        for path in self._output_dirs():
            shutil.rmtree(path, ignore_errors=True)
        return False


__all__ = ["KEEP_ENV_VAR", "TrialSandbox", "keep_trial_scratch"]
