"""A run or project already in the catalog stops ``hmp data import`` with exit 12."""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli.commands.data import import_cmd
from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT
from hydromodpy.core.exceptions import ImportConflictError


def test_a_duplicate_import_exits_as_a_write_conflict(monkeypatch, capsys) -> None:
    def _refuse(*_args, **_kwargs):
        raise ImportConflictError("Simulation 's1' is already in this catalog.")

    monkeypatch.setattr("hydromodpy.cli._workers.data.import_package", _refuse)
    args = argparse.Namespace(
        package="run.hmp",
        workspace=None,
        as_project=None,
        dry_run=False,
        force=False,
        verbose=0,
        quiet=0,
        log_level=None,
    )
    with pytest.raises(SystemExit) as caught:
        import_cmd.run(args)
    assert caught.value.code == EXIT_WRITE_CONFLICT
    assert "already in this catalog" in capsys.readouterr().err
