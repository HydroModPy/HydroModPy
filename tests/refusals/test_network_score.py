"""Scoring the stream network of a stored run refuses what the run cannot give, by name."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.results.derive.stream_network.run_score import network_score_table
from hydromodpy.results.storage.contract import RUN_RESOLVED_CONFIG_FILENAME
from tests._helpers.transient_network_run import transient_run
from tests.unit.display._network_comparison_run import comparison_run

FILE_MAP = '[searched_under.outputs.net]\nsupport = "network"\nmap = {{ complete = "{path}" }}\n'


def _sealed(run: Any, folder: Path, text: str) -> Any:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RUN_RESOLVED_CONFIG_FILENAME).write_text(text, encoding="utf-8")
    run.dir = folder
    return run


def _without_release(folder: Path) -> Any:
    run = comparison_run(with_release=False)
    run.dir = folder
    return run


def _without_recharge(folder: Path) -> Any:
    run = comparison_run(kept_recharge=False)
    run.dir = folder
    return run


def _missing_file(folder: Path) -> Any:
    return _sealed(comparison_run(), folder, FILE_MAP.format(path="gone.gpkg"))


def _cut_to_a_mask(folder: Path) -> Any:
    folder.mkdir(parents=True, exist_ok=True)
    run = comparison_run()
    run.hydrographic_network("reference").to_file(folder / "map.gpkg")
    run.config_snapshot = {"data": {"hydrography": {"mask_path": "mask.shp"}}}
    return _sealed(run, folder, FILE_MAP.format(path=(folder / "map.gpkg").as_posix()))


def _no_year_in_window(folder: Path) -> Any:
    run = transient_run()
    run.dir = folder
    return run


REFUSALS: list[tuple[str, Callable[[Path], Any], dict[str, Any], type[Exception], str]] = [
    ("no_release_flux", _without_release, {}, NothingThereError, "release_flux"),
    ("map_file_gone", _missing_file, {}, NothingThereError, "not there any more"),
    ("cut_to_mask_path", _cut_to_a_mask, {}, NothingThereError, "mask_path"),
    (
        "window_without_year",
        _no_year_in_window,
        {"window": ("2001-03-01", "2001-12-31")},
        NothingThereError,
        "no complete calendar year",
    ),
    ("unknown_output", _without_release, {"output": "net"}, NothingThereError, "sealed no network"),
    ("no_kept_recharge", _without_recharge, {}, NothingThereError, "criterion mean recharge"),
]


@pytest.mark.parametrize(
    ("build", "kwargs", "error", "fragment"),
    [row[1:] for row in REFUSALS],
    ids=[row[0] for row in REFUSALS],
)
def test_refusal(tmp_path, build, kwargs, error, fragment) -> None:
    run = build(tmp_path / "run")
    with pytest.raises(error, match=fragment):
        network_score_table(run, project_root=tmp_path, **kwargs)
