"""``python -m tools.dev examples manifest`` rewrites the shipped example catalog."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.project.examples.manifest import catalog_path
from tools.dev.__main__ import main


def test_the_manifest_rewrites_the_catalog(capsys, tmp_path: Path) -> None:
    output = tmp_path / "catalog.toml"

    main(["examples", "manifest", "--to", str(output)])

    assert output.read_text(encoding="utf-8") == catalog_path().read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Wrote" in out
    assert str(output) in out
    assert " file(s), " in out
