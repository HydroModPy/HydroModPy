"""Protocol for output adapters that ingest solver files into a store."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class OutputAdapter(Protocol):
    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
    ) -> None: ...
