from __future__ import annotations

from hydromodpy.analysis.comparison.web.sections.io import (
    _boussinesq_method_text,
    _initial_condition_text,
)


def test_boussinesq_method_text_documents_direct_petsc_vi_obstacle() -> None:
    text = _boussinesq_method_text(
        {
            "runtime_backend": "petsc",
            "surface_interaction_model": "vi_obstacle",
            "vi_substeps_per_period": 4,
            "vi_substep_on_failure": True,
            "runtime_tol_residual_inf": 1.0e-6,
        }
    )

    assert "backend PETSc complet" in text
    assert "surface_interaction_model=vi_obstacle" in text
    assert "solveur PETSc SNESVI direct" in text
    assert "4 sous-pas par periode" in text
    assert "retry adaptatif active" in text


def test_initial_condition_text_documents_direct_petsc_vi_obstacle() -> None:
    text = _initial_condition_text(
        {
            "runtime_backend": "petsc",
            "surface_interaction_model": "vi_obstacle",
            "ic": {"type": "steady_state"},
        }
    )

    assert "PETSc SNESVI" in text
    assert "vi_obstacle directe" in text
