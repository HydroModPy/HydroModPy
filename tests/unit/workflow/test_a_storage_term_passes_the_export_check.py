"""Step 0 accepts the budget terms a solver writes but the registry once left out."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.config_kit.export_spec import ExportKind, ExportRequest
from hydromodpy.results.exporters.vocabulary import static_export_names
from hydromodpy.workflow.steps.validate import check_export_variables

TERMS = ("storage", "storage_ss", "storage_sy", "evapotranspiration")


@pytest.mark.parametrize("term", TERMS)
def test_the_vocabulary_holds_the_term_as_a_field(term: str) -> None:
    assert static_export_names()[term] is ExportKind.field


def test_a_block_naming_the_terms_passes_step_zero() -> None:
    cfg = SimpleNamespace(
        simulation=SimpleNamespace(name="demo"),
        export=[ExportRequest(variables=list(TERMS))],
    )
    check_export_variables(cfg)
