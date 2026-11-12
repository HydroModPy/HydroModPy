"""The Zenodo deposit metadata is a view of the seal, and invents nothing.

A published copy carries one ``.zenodo.json`` at its root. Every fact it holds
comes from the seal of the run or from the ``[publication]`` table of the
project, and a fact neither carries is left out rather than guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hydromodpy.results.export.zenodo import zenodo_metadata, zenodo_metadata_of_project
from hydromodpy.results.identity import Identity
from hydromodpy.results.publication import PublicationConfig
from hydromodpy.results.record.checks import Checks
from hydromodpy.results.record.manifest import (
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    ManifestSite,
    RunSeal,
)
from hydromodpy.schema.lineage import Lineage, Replay

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
VERSION = "2.1.0a1"
SIM_ID = "3" * 32


def _run(**overrides: object) -> ManifestRun:
    """One completed run of the demo project."""
    payload: dict[str, object] = {
        "sim_id": SIM_ID,
        "name": "demo",
        "name_stem": "demo",
        "version": 1,
        "status": "completed",
        "project": "lakeres",
        "case_id": "demo",
        "rel_dir": "runs/demo",
        "attempt": 1,
        "attempt_id": "a" * 32,
        "solver": "modflow6",
        "created_at": NOW,
    }
    payload.update(overrides)
    return ManifestRun(**payload)  # type: ignore[arg-type]


def _demo_seal() -> RunSeal:
    """The seal of the demo run, holding only what a plain run writes."""
    return RunSeal(
        sealed_at=NOW,
        run=_run(),
        site=ManifestSite(name="kerouer", fingerprint="f" * 16),
        geometry=ManifestGeometry(),
        period=ManifestPeriod(),
        config=ManifestConfig(file="config.toml"),
        identity=Identity(
            site="kerouer",
            case_id="demo",
            sim_id=SIM_ID,
            attempt_id="a" * 32,
            hydromodpy_version=VERSION,
        ),
        checks=Checks(),
    )


def _published_seal() -> RunSeal:
    """A seal carrying a DOI, a description and the two runs it derives from."""
    return _demo_seal().model_copy(
        update={
            "run": _run(
                name="demo.v2",
                name_stem="demo",
                version=2,
                description="Transient run of the Kerouer basin.",
                scientific_objective="Compare the intermittent streamflow signal.",
                license="etalab-2.0",
                doi="10.5281/zenodo.1000000",
            ),
            "lineage": Lineage(
                parent_sim_id=SIM_ID,
                replay=Replay(
                    of="4" * 32,
                    source="run",
                    source_version="2.0.0",
                    basis="stored",
                    **{"class": "bit"},
                ),
            ),
        }
    )


def test_the_licence_of_the_run_is_the_fallback_of_a_record_without_one():
    metadata = zenodo_metadata(_published_seal(), PublicationConfig(creators=["A. Author"]))

    assert metadata["license"] == "etalab-2.0"


def test_one_identifier_named_twice_is_written_once():
    seal = _published_seal().model_copy(
        update={
            "lineage": Lineage(
                parent_sim_id=SIM_ID,
                replay=Replay(of=SIM_ID, source="run", source_version="2.0.0", basis="none"),
            )
        }
    )

    metadata = zenodo_metadata(seal)

    identifiers = [row["identifier"] for row in metadata["related_identifiers"]]
    assert identifiers.count(SIM_ID) == 1


@pytest.mark.parametrize(
    ("publication", "expected"),
    [
        pytest.param(
            {},
            {"upload_type": "dataset", "title": "lake", "version": "3"},
            id="nothing_declared",
        ),
        pytest.param(
            {"license": "etalab-2.0"},
            {
                "upload_type": "dataset",
                "title": "lake",
                "version": "3",
                "license": "etalab-2.0",
            },
            id="licence_only",
        ),
        pytest.param(
            {"creators": ["Ada L.", "Bo K."]},
            {
                "upload_type": "dataset",
                "title": "lake",
                "version": "3",
                "creators": [{"name": "Ada L."}, {"name": "Bo K."}],
            },
            id="creators_only",
        ),
        pytest.param(
            {"license": "CC-BY-4.0", "creators": ["Ada L."]},
            {
                "upload_type": "dataset",
                "title": "lake",
                "version": "3",
                "creators": [{"name": "Ada L."}],
                "license": "CC-BY-4.0",
            },
            id="both",
        ),
    ],
)
def test_the_metadata_of_a_project_comes_from_the_publication_table(publication, expected):
    metadata = zenodo_metadata_of_project(
        PublicationConfig(**publication), title="lake", version="3"
    )

    assert metadata == expected
