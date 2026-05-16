"""Machine-wide projects namespace -- wraps ``index.duckdb``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class ProjectsNamespace:
    """Read-mostly facade over ``<state_dir>/index.duckdb``.

    Opens the index in read-only mode so concurrent ``hmp run`` writers
    keep the write-lock. The index is opened lazily on first call.
    """

    def __init__(self) -> None:
        self._index: Any = None

    def _open(self) -> Any:
        if self._index is None:
            from hydromodpy.core.state.global_index import GlobalIndex

            self._index = GlobalIndex(read_only=True)
        return self._index

    def list(self) -> pd.DataFrame:
        """Return all registered workspaces with their last-scan timestamp."""
        return self._open().list_workspaces()

    def find(self, **filters: Any) -> pd.DataFrame:
        """Federated simulation search across every registered workspace."""
        index = self._open()
        try:
            return index.find(**filters)
        finally:
            # The federation view is rebuilt on every find() call; no extra
            # close needed here, just hand control back to the caller.
            pass

    def search(self, term: str) -> pd.DataFrame:
        """Full-text search across simulation descriptions."""
        return self._open().search(term)

    def close(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None


__all__ = ["ProjectsNamespace"]
