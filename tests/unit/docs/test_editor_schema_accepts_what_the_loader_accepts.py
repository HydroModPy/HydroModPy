"""The published schema accepts every file the loader accepts.

An editor checks one TOML file against ``hydromodpy-schema.json`` through a
``#:schema`` header. A file is not the model: it may extend another one with
``base_config``, omit every key it does not change, write ``<key>__append`` or
``<key>__delete``, and write a quantity as text with a unit. A schema that
refuses these puts a red underline under a file that runs, and the author learns
to ignore the editor.

The example project is the reference corpus: its files are loaded by the real
loader in other tests, so each one must also pass here.
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
from jsonschema.validators import Draft202012Validator

from hydromodpy.config.schema_export import editor_schema, export_schema

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
SCHEMA_PATH = ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"


def _as_an_editor_sends_it(value: Any) -> Any:
    """Return *value* with TOML dates as text, as Taplo hands them to a validator."""
    if isinstance(value, datetime.date | datetime.datetime | datetime.time):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _as_an_editor_sends_it(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_an_editor_sends_it(item) for item in value]
    return value


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return Draft202012Validator(editor_schema())


def _problems(validator: Draft202012Validator, text: str) -> list[str]:
    document = _as_an_editor_sends_it(tomllib.loads(text))
    return [
        f"{'.'.join(str(p) for p in error.absolute_path)}: {error.message[:120]}"
        for error in validator.iter_errors(document)
    ]


EXAMPLE_FILES = sorted(EXAMPLE.rglob("*.toml"))


def test_the_example_corpus_is_found() -> None:
    assert len(EXAMPLE_FILES) >= 10


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_every_example_file_validates(validator: Draft202012Validator, path: Path) -> None:
    assert _problems(validator, path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_the_published_schema_validates_every_example_file(path: Path) -> None:
    import json

    published = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert _problems(published, path.read_text(encoding="utf-8")) == []


ACCEPTED = {
    "base_config": 'base_config = "step1_minimal.toml"\n',
    "append a list": 'base_config = "a.toml"\n[display]\nfigures__append = ["x"]\n',
    "append a table list": 'export__append = [{ format = "csv" }]\n',
    "delete a section": 'base_config = "a.toml"\nmesh_catchment__delete = true\n',
    "delete a key in a section": "[data]\nrecharge__delete = true\n",
    "delete a key the variant lacks": (
        '[domain.depth_model]\nkind = "raster_thickness"\nthickness__delete = true\n'
    ),
    "quantity as text": '[geographic.catchment]\ncatch_def = "from_outlet_coord"\nsnap_dist = "150 m"\n',
    "quantity with a converted unit": '[domain.depth_model]\nkind = "constant_thickness"\nthickness = "0.03 km"\n',
    "quantity as a number": '[domain.depth_model]\nkind = "constant_thickness"\nthickness = 30\n',
    "date as a TOML date": "[simulation.time]\nstart_datetime = 2019-01-01\n",
    "no required key": '[flow]\nflow_regime = "transient"\n',
    "flat initial condition": '[flow.ic]\ntype = "steady_state"\n',
    "item without its tag": '[data.recharge]\nsources = [{ station_ids = ["A"] }]\n',
}


@pytest.mark.parametrize("name", sorted(ACCEPTED))
def test_a_form_the_loader_reads_is_accepted(validator: Draft202012Validator, name: str) -> None:
    assert _problems(validator, ACCEPTED[name]) == []


REFUSED = {
    "unknown section": "[no_such_section]\nx = 1\n",
    "unknown key": "[flow]\nno_such_key = 1\n",
    "wrong enum value": '[flow]\nflow_regime = "transiant"\n',
    "text that is not a quantity": (
        '[domain.depth_model]\nkind = "constant_thickness"\nthickness = "deep"\n'
    ),
    "quantity out of range": '[domain.depth_model]\nkind = "constant_thickness"\nthickness = -5\n',
    "delete that is not true": "export__delete = false\n",
    "append on a key that is no list": "flow__append = [1]\n",
    "base_config that is no path": "base_config = 3\n",
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_a_mistake_is_still_flagged(validator: Draft202012Validator, name: str) -> None:
    assert _problems(validator, REFUSED[name]) != []


def test_the_editor_schema_is_valid_json_schema_2020_12() -> None:
    schema = editor_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_the_model_schema_keeps_its_required_keys() -> None:
    """Frontends and the lockfile read the model schema, not the editor one."""
    assert "workspace" in export_schema().get("required", [])
    assert "required" not in editor_schema()
    assert "base_config" not in export_schema()["properties"]


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("taplo") is None, reason="taplo is not installed")
class TestTaplo:
    """The tool behind Even Better TOML reads the same files the same way.

    ``jsonschema`` does not assert string formats and Taplo does, so a schema
    that passes the first can still underline a date in the editor.
    """

    @staticmethod
    def _lint(tmp_path: Path, text: str) -> int:
        target = tmp_path / "file.toml"
        target.write_text(text, encoding="utf-8")
        done = subprocess.run(
            ["taplo", "lint", "--schema", SCHEMA_PATH.as_uri(), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode

    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
    def test_every_example_file_lints(self, tmp_path: Path, path: Path) -> None:
        assert self._lint(tmp_path, path.read_text(encoding="utf-8")) == 0

    @pytest.mark.parametrize("name", sorted(ACCEPTED))
    def test_a_form_the_loader_reads_lints(self, tmp_path: Path, name: str) -> None:
        assert self._lint(tmp_path, ACCEPTED[name]) == 0

    @pytest.mark.parametrize("name", sorted(REFUSED))
    def test_a_mistake_is_flagged(self, tmp_path: Path, name: str) -> None:
        assert self._lint(tmp_path, REFUSED[name]) != 0
