"""``hmp completion SHELL`` prints the script that argcomplete writes for the two program names."""

from __future__ import annotations

import argparse

import pytest

from hydromodpy.cli.commands import completion


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_the_script_is_the_one_argcomplete_writes(capsys, shell: str) -> None:
    argcomplete = pytest.importorskip("argcomplete")

    completion.run(argparse.Namespace(shell=shell))

    printed = capsys.readouterr().out
    assert printed == argcomplete.shellcode(["hmp", "hydromodpy"], shell=shell)
    assert "hmp" in printed and "hydromodpy" in printed
