"""The lineage block links by ids, names its kind, and refuses what it does not know."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.schema.lineage import Replay


def test_a_replay_without_a_basis_has_no_class():
    with pytest.raises(ValidationError, match="class"):
        Replay(of="s", source="copy", source_version="2.0.0", basis="none", class_="bit")


def test_a_replay_with_a_basis_states_a_class():
    with pytest.raises(ValidationError, match="class"):
        Replay(of="s", source="run", source_version="2.0.0", basis="float64")
