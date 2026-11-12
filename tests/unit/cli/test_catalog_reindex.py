"""``hmp catalog reindex``: the index comes back from the run directories."""

from __future__ import annotations

import importlib
import sys

from ._hmp import run_main as _run


def test_reindex_appears_in_the_catalog_help(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "--help"])

    assert code == 0
    assert "reindex" in capsys.readouterr().out
