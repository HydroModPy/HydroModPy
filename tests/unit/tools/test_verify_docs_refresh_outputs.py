from __future__ import annotations

from tools.verify_docs_refresh_outputs import (
    RefreshPathPolicy,
    parse_porcelain_paths,
    partition_changed_paths,
)


def test_parse_porcelain_paths_handles_modified_untracked_and_rename() -> None:
    status = (
        " M docs/readthedocs/source/capability_gallery/index.rst\n"
        "?? validation_cases/reports/latest/modflow6_both.json\n"
        "R  old_name.txt -> tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json\n"
    )

    assert parse_porcelain_paths(status) == (
        "docs/readthedocs/source/capability_gallery/index.rst",
        "validation_cases/reports/latest/modflow6_both.json",
        "tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json",
    )


def test_partition_changed_paths_uses_default_allowlist() -> None:
    changed = (
        "docs/readthedocs/source/capability_gallery/cases/demo.rst",
        "docs/readthedocs/source/_static/capability_gallery/validation/demo.png",
        "validation_cases/reports/latest/modflow6_both.json",
        "tools/doc_gallery/manifests/xt3d_irregular_tri_method_choice_report.json",
        "README.md",
    )

    allowed, unexpected = partition_changed_paths(changed)

    assert allowed == changed[:-1]
    assert unexpected == ("README.md",)


def test_partition_changed_paths_honors_custom_policy() -> None:
    changed = ("custom/generated/report.json", "notes.txt")
    policy = RefreshPathPolicy(
        allowed_prefixes=("custom/generated/",),
        allowed_files=("notes.txt",),
    )

    allowed, unexpected = partition_changed_paths(changed, policy=policy)

    assert allowed == changed
    assert unexpected == ()
