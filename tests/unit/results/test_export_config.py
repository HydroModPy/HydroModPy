"""``[[export]]`` on the root config: an array of requests, each refusal naming its block."""

from __future__ import annotations

import re
import textwrap
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


def test_a_request_written_as_a_table_is_refused_with_the_spelling_to_write(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigValidationError, match=r"write \[\[export\]\]"):
        _load(tmp_path, '[export]\nvariables = "head"\nformat = "netcdf"\n')


def test_the_loader_reads_an_empty_document_as_no_request() -> None:
    assert load_export_requests(None) == []
    assert load_export_requests([]) == []


def test_export_is_a_top_level_list_on_the_root_config() -> None:
    field = HydroModPyConfig.model_fields["export"]
    assert field.default_factory is list


def test_results_config_has_no_export() -> None:
    from hydromodpy.solver.base.results_config import ResultsConfig

    assert "export" not in ResultsConfig.model_fields


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
