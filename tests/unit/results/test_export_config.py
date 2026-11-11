"""``[[export]]`` on the root config: an array of requests, each refusal naming its block."""

from __future__ import annotations

import re
import textwrap
import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests

_HEAD = """\
[workspace]

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
        format = "rocrate"
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


def test_the_old_table_of_toggles_is_refused_as_a_pre_release_form(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="export.geotiff"):
        _load(tmp_path, '[export]\ngeotiff = true\nvariables = ["head"]\ntime = 3\n')


def test_the_loader_reads_an_empty_document_as_no_request() -> None:
    assert load_export_requests(None) == []
    assert load_export_requests([]) == []


def test_export_is_a_top_level_list_on_the_root_config() -> None:
    field = HydroModPyConfig.model_fields["export"]
    assert field.default_factory is list


def test_results_config_has_no_export() -> None:
    from hydromodpy.solver.base.results_config import ResultsConfig

    assert "export" not in ResultsConfig.model_fields


def test_a_destination_written_as_a_string_reads_as_the_list_of_one(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[[export]]\nvariables = "head"\ndeliver_to = "/srv/depot/"\n')

    assert cfg.export[0].deliver_to == ["/srv/depot/"]


def test_the_resolved_config_writes_no_destination_at_its_default(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[[export]]\nvariables = "head"\n')
    frozen = cfg.to_toml(tmp_path / "resolved.toml", profile="expert")

    resolved = tomllib.loads(frozen.read_text(encoding="utf-8"))
    assert "deliver_to" not in resolved["export"][0]
    assert HydroModPyConfig.from_toml(frozen).export[0].deliver_to is None


def test_deliver_to_survives_the_resolved_config_round_trip(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[[export]]\nvariables = "head"\ndeliver_to = "/srv/depot/"\n')
    frozen = cfg.to_toml(tmp_path / "resolved.toml", profile="expert")

    assert HydroModPyConfig.from_toml(frozen).export == cfg.export


DELIVERY_REFUSED = [
    pytest.param('"livrables/nancon"', "is a relative path", id="relative path"),
    pytest.param(
        '"https://zenodo.org/deposit/1"',
        "uses https://, which HydroModPy does not deliver to",
        id="other scheme",
    ),
    pytest.param(
        '"ftp://bb:secret@data.example.org/depot/"',
        "carries a user or a password",
        id="identity in the address",
    ),
    pytest.param(
        '"ftp://data.example.org/depot/?case=a"',
        "carries a query or a fragment",
        id="query",
    ),
    pytest.param('"ftp:///depot/"', "names no host", id="no host"),
    pytest.param("[]", "deliver_to is empty", id="empty list"),
]


@pytest.mark.parametrize(("written", "phrase"), DELIVERY_REFUSED)
def test_a_destination_no_delivery_reaches_is_refused_with_its_phrase(
    tmp_path: Path, written: str, phrase: str
) -> None:
    body = f'[[export]]\nvariables = "head"\ndeliver_to = {written}\n'

    with pytest.raises(ConfigValidationError, match=re.escape(phrase)):
        _load(tmp_path, body)


DELIVERY_UNANSWERABLE = [
    pytest.param(
        '[[export]]\nvariables = "head"\ndeliver_to = ["/srv/depot/", "/srv/depot/"]\n',
        "deliver_to names '/srv/depot/' twice.",
        id="same destination twice",
    ),
    pytest.param(
        '[[export]]\nvariables = "head"\ndeliver_to = "/srv/depot/head.tif"\n',
        "names one remote file",
        id="file destination without file",
    ),
    pytest.param(
        '[[export]]\nvariables = "all"\nformat = "rocrate"\ndeliver_to = "/srv/depot/"\n',
        "a view is delivered from exports",
        id="view without folder or file",
    ),
]


@pytest.mark.parametrize(("body", "phrase"), DELIVERY_UNANSWERABLE)
def test_a_delivery_the_block_cannot_answer_is_refused(
    tmp_path: Path, body: str, phrase: str
) -> None:
    with pytest.raises(ConfigValidationError, match=re.escape(phrase)):
        _load(tmp_path, body)


def test_a_view_with_a_folder_delivers_the_files_it_writes(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        """\
        [[export]]
        variables = "all"
        format = "rocrate"
        folder = "views"
        deliver_to = "/srv/depot/"
        """,
    )

    assert cfg.export[0].deliver_to == ["/srv/depot/"]


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
