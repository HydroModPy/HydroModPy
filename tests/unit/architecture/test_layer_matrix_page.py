"""Gate for the generated layer-matrix page fragment.

The page used to be hand-written prose reciting ``layer_matrix.yaml``. It had
drifted: the ``discretization`` row was missing, a ``validity_frame`` row was
present although it is neither a key of the contract nor a package on disk, and
three rows dropped an edge their entry grants. The contract had 33 commits over
the window against 4 on the page reciting it.

Two assertions, in the order that matters. First the contract must be sound,
because a generator republishes whatever it is given. Only then is the rendered
copy compared with the committed one.
"""

from __future__ import annotations

from tools.doc_contracts import (
    LAYER_MATRIX_PAGE,
    REPO_ROOT,
    assert_layer_matrix_inputs,
    load_layer_matrix,
    render_layer_matrix,
)


def test_the_layer_contract_is_sound() -> None:
    """Every declared layer is a real package, every edge names a real layer."""
    problems = assert_layer_matrix_inputs(load_layer_matrix())
    assert problems == [], (
        "tests/unit/architecture/layer_matrix.yaml declares something that does not exist:\n  - "
        + "\n  - ".join(problems)
    )


def test_committed_layer_matrix_page_matches_the_contract() -> None:
    committed = (REPO_ROOT / LAYER_MATRIX_PAGE).read_text(encoding="utf-8")
    expected = render_layer_matrix(load_layer_matrix())
    assert committed == expected, (
        f"{LAYER_MATRIX_PAGE.as_posix()} is stale. "
        "Run `python -m tools.doc_contracts` and commit the result."
    )
