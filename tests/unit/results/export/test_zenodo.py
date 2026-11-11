"""The Zenodo deposit metadata is a view of the seal, and invents nothing.

A published copy carries one ``.zenodo.json`` at its root. Every fact it holds
comes from the seal of the run or from the ``[publication]`` table of the
project, and a fact neither carries is left out rather than guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hydromodpy.results.export.zenodo import (
    ZENODO_UPLOAD_TYPE,
    zenodo_metadata,
    zenodo_metadata_of_project,
)
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


def test_the_demo_seal_fills_the_deposit_form_from_what_it_holds():
    metadata = zenodo_metadata(_demo_seal())

    assert metadata["upload_type"] == ZENODO_UPLOAD_TYPE == "dataset"
    assert metadata["title"] == "demo"
    assert metadata["version"] == "1"
    assert metadata["description"] == "Run demo of project lakeres."
    assert metadata["keywords"] == ["HydroModPy", "lakeres", "demo", "modflow6", "kerouer"]


def test_a_fact_neither_the_run_nor_the_record_carries_is_left_out():
    metadata = zenodo_metadata(_demo_seal())

    assert "creators" not in metadata
    assert "license" not in metadata
    assert "related_identifiers" not in metadata


def test_the_publication_table_supplies_the_creators_and_the_licence():
    record = PublicationConfig(license="CC-BY-4.0", creators=["A. Author", "B. Author"])

    metadata = zenodo_metadata(_published_seal(), record)

    assert metadata["creators"] == [{"name": "A. Author"}, {"name": "B. Author"}]
    assert metadata["license"] == "CC-BY-4.0"


def test_the_licence_of_the_run_is_the_fallback_of_a_record_without_one():
    metadata = zenodo_metadata(_published_seal(), PublicationConfig(creators=["A. Author"]))

    assert metadata["license"] == "etalab-2.0"


def test_the_description_comes_from_the_run_and_the_objective_is_the_fallback():
    seal = _demo_seal()

    described = zenodo_metadata(
        seal.model_copy(update={"run": _run(description="A sentence.", scientific_objective="B.")})
    )
    objective_only = zenodo_metadata(
        seal.model_copy(update={"run": _run(scientific_objective="A comparison.")})
    )

    assert described["description"] == "A sentence."
    assert objective_only["description"] == "A comparison."


def test_the_identifiers_link_the_record_it_is_derived_from_and_the_run_it_replayed():
    metadata = zenodo_metadata(_published_seal())

    assert metadata["related_identifiers"] == [
        {"identifier": "10.5281/zenodo.1000000", "relation": "isIdenticalTo", "scheme": "doi"},
        {"identifier": SIM_ID, "relation": "isDerivedFrom", "scheme": "other"},
        {"identifier": "4" * 32, "relation": "isDerivedFrom", "scheme": "other"},
    ]


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


def test_the_keywords_of_a_seal_without_a_site_leave_it_out():
    seal = _demo_seal().model_copy(
        update={
            "site": None,
            "identity": Identity(
                case_id="demo",
                sim_id=SIM_ID,
                attempt_id="a" * 32,
                hydromodpy_version=VERSION,
            ),
        }
    )

    metadata = zenodo_metadata(seal)

    assert "kerouer" not in metadata["keywords"]
    assert metadata["keywords"][0] == "HydroModPy"


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
