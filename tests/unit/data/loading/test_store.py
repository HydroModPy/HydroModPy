"""The data store of a workspace is the ``data/`` folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.loading.store import DataStore


@pytest.mark.fast
def test_a_workspace_without_a_data_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"Not a workspace: the folder 'data/' is not in"):
        DataStore(workspace_root=tmp_path)
