"""``[[export]]`` on the root config: an array of requests, each refusal naming its block."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.export_spec import ExportRequest, load_export_requests
from hydromodpy.core.exceptions import ConfigValidationError

_HEAD = """\
[workspace]
project_root = "{root}"

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

"""


def _load(tmp_path: Path, body: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(
        _HEAD.format(root=tmp_path.as_posix()) + textwrap.dedent(body), encoding="utf-8"
    )
    return HydroModPyConfig.from_toml(path)


def test_a_config_without_export_writes_nothing(tmp_path: Path) -> None:
    assert _load(tmp_path, "").export == []


def test_the_blocks_load_in_the_order_of_the_file(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        """\
        [[export]]
        variables = ["head", "watertable_depth"]
        time = 2002-10-15

        [[export]]
        variables = "all"
        format = "package"
        """,
    )

    assert [request.variables for request in cfg.export] == [
        ["head", "watertable_depth"],
        "all",
    ]
    # A bare TOML date reads as the date it names.
    assert cfg.export[0].time == "2002-10-15"


def test_a_refusal_names_its_block(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"export\[1\].*time and period"):
        _load(
            tmp_path,
            """\
            [[export]]
            variables = "head"

            [[export]]
            variables = "head"
            time = "last"
            period = ["2000-01-01", "2000-12-31"]
            """,
        )


def test_a_misspelt_key_is_refused_with_its_block(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match=r"export\[0\]\.fomat"):
        _load(tmp_path, '[[export]]\nvariables = "head"\nfomat = "netcdf"\n')


def test_a_request_written_as_a_table_is_refused_with_the_spelling_to_write(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigValidationError, match=r"write \[\[export\]\]"):
        _load(tmp_path, '[export]\nvariables = "head"\nformat = "netcdf"\n')


def test_the_old_table_of_toggles_still_loads(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[export]\ngeotiff = true\nvariables = ["head"]\ntime = 3\n')

    assert cfg.export == [ExportRequest(variables=["head"], format="geotiff", time=3)]


def test_the_loader_reads_an_empty_document_as_no_request() -> None:
    assert load_export_requests(None) == []
    assert load_export_requests([]) == []


def test_export_is_a_top_level_list_on_the_root_config() -> None:
    field = HydroModPyConfig.model_fields["export"]
    assert field.default_factory is list


def test_results_config_has_no_export() -> None:
    from hydromodpy.simulation.planning.results_config import ResultsConfig

    assert "export" not in ResultsConfig.model_fields


def test_the_requests_survive_the_resolved_config_round_trip(tmp_path: Path) -> None:
    """A run seals its resolved config and a resume loads it back."""
    cfg = _load(
        tmp_path,
        """\
        [[export]]
        variables = "discharge"
        period = ["2001-01-01", "2002-12-31"]

        [[export]]
        variables = "watertable_depth"
        time = "last"
        file = "depth_wgs84.tif"
        crs = "EPSG:4326"
        """,
    )
    frozen = cfg.to_toml(tmp_path / "resolved.toml", profile="expert")

    assert HydroModPyConfig.from_toml(frozen).export == cfg.export
