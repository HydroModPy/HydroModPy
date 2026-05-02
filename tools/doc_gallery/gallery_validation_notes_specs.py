"""Additional validation-gallery narrative pages."""

from __future__ import annotations

from .gallery_schema import GalleryCaseSpec, GalleryImageAsset


def build_validation_note_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
        GalleryCaseSpec(
            slug="modflow6_irregular_tri_xt3d_method_choice",
            title="MODFLOW 6 Irregular Triangles: Why XT3D Is The Default",
            category="validation",
            deck=(
                "Pedagogical comparison of MODFLOW 6 irregular triangles with and without "
                "XT3D on the steady analytical strip benchmarks affected by the default change."
            ),
            summary=(
                "This note explains why HydroModPy now auto-enables XT3D on unstructured "
                "MODFLOW 6 meshes, and what that choice buys in RMSE versus local runtime."
            ),
            what_it_shows=(
                "the same 11 steady analytical validation cases run twice: once with XT3D forcibly disabled, once with the current HydroModPy auto-default,",
                "where the large RMSE reductions come from in practical terms, especially on non-orthogonal strip meshes where sloping-support geometry must be reconstructed across oblique polygon connections,",
                "the local runtime impact observed in the `hydromodpy-kpg` environment so the numerical benefit can be weighed against execution time.",
            ),
            reproduction_command=(
                "python -m tools.doc_gallery --only modflow6_irregular_tri_xt3d_method_choice"
            ),
            source_paths=(
                "tools/doc_gallery/gallery_validation_notes_specs.py",
                "tools/doc_gallery/xt3d_irregular_tri_diagnostics.py",
                "tools/doc_gallery/disable_xt3d_sitecustomize/sitecustomize.py",
                "tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json",
                "tools/doc_gallery/update_gallery.py",
                "hydromodpy/solver/modflow6/modflow6.py",
                "hydromodpy/solver/modflow6/modflow6_config.py",
                "tests/unit/solver/modflow_nwt/test_modflow_config.py",
                "tests/unit/solver/test_modflow6_boundary_conditions.py",
                "validation_cases/README.md",
            ),
            generator="xt3d_method_choice_case",
            image_assets=(
                GalleryImageAsset(
                    filename="modflow6_irregular_tri_xt3d_method_choice_tradeoff.png",
                    caption=(
                        "Before/after XT3D comparison on the 11 steady analytical validation "
                        "cases that use MODFLOW 6 irregular triangles."
                    ),
                    alt_text=(
                        "RMSE and runtime comparison for MODFLOW 6 irregular triangles "
                        "with and without XT3D"
                    ),
                ),
            ),
            case_setup=(
                "Uses the steady analytical validation subset that exposes `modflow6_irregular_tri`.",
                "Compares the same solver family on the same meshes; only the XT3D flux formulation changes.",
                "Measures wall-clock durations around the full validation comparison call in the local `hydromodpy-kpg` environment.",
            ),
            how_to_read=(
                "Read the RMSE columns first: those numbers show whether the irregular-triangle variant better matches the analytical reference once XT3D is active.",
                "Then read the timing columns as local guidance only. They are useful for relative cost, not as portable performance claims.",
                "For the 1D strip cases, remember that the committed comparison workflow collapses native-cell outputs to one x-profile before computing the published RMSE. That makes the gallery metric good for regression tracking, but smoother than native cell-by-cell centroid errors on the DISV mesh.",
                "The two regressed drainage cases stay below their current tolerances; they are the main caution behind keeping XT3D as an auto default rather than silently pretending it is universally better on every metric.",
            ),
            next_steps=(
                "Open the individual validation pages linked from the validation landing page when you need the full solver-specific figures behind one row of the table.",
                "If a project uses structured grids only, keep the structured default path: XT3D is intentionally not auto-enabled there.",
                "If a specific unstructured scenario needs the previous behaviour, set `mf6_enable_xt3d = false` explicitly in `[modflow6.runtime]`.",
            ),
            walkthrough_doc="getting_started/reading-results-pages",
            walkthrough_title="How to read gallery, comparison, and validation pages",
            metadata={
                "process_family": "flow",
                "process_family_label": "Flow",
                "validation_family": "xt3d_method_choice_irregular_meshes",
                "validation_family_label": "XT3D Choice For Irregular MF6 Meshes",
                "validation_family_order": 35,
                "reference_type": "diagnostic_comparison",
                "reference_type_label": "Diagnostic Comparison",
                "regime": "steady",
                "dimension": "1d",
                "report_source_path": "tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json",
                "lead_image_filenames": [
                    "modflow6_irregular_tri_xt3d_method_choice_tradeoff.png"
                ],
            },
        ),
    )


__all__ = ["build_validation_note_specs"]
