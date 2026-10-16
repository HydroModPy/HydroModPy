"""A view of a run states the licence its frozen configuration declares, and nothing else.

``[publication] license`` in ``config.toml`` names the licence and the
creators; a run whose configuration declares none says
``LicenseRef-undetermined``, never a default.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.export.directory import context_from_directory, publication_of
from tests.unit.results._run_record_factory import make_record


def _sealed(tmp_path: Path, config: str | None) -> Path:
    record = make_record()
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    if config is not None:
        (run_dir / "config.toml").write_text(config, encoding="utf-8")
    return run_dir


def test_the_declared_licence_and_creators_reach_the_view(tmp_path) -> None:
    run_dir = _sealed(
        tmp_path, '[publication]\nlicense = "CC-BY-4.0"\ncreators = ["A. Author", "B. Author"]\n'
    )

    context = context_from_directory(run_dir)

    assert context.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert context.creator_name == "A. Author, B. Author"


def test_a_run_that_declares_nothing_stays_undetermined(tmp_path) -> None:
    for config in (None, "[simulation]\nname = 'x'\n"):
        run_dir = _sealed(tmp_path / str(config is None), config)
        context = context_from_directory(run_dir)
        assert context.license_url == "LicenseRef-undetermined"
        assert context.creator_name is None
        assert publication_of(run_dir).license is None
