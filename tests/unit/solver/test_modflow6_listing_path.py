"""MF6 listing-file resolution: the mass balance follows the name MF6 was given."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.solver.modflow6.build import mf6_safe_name
from hydromodpy.solver.modflow6.extractors.flow import _listing_path


def test_short_name_listing_matches_the_run_name() -> None:
    assert _listing_path(Path("/out"), "canut_paper_mf6") == Path("/out/canut_paper_mf6.lst")


def test_long_name_listing_follows_the_truncated_model_name() -> None:
    # The .hds/.cbc keep the full run name but MF6 wrote the listing under the
    # 16-char model name, so a raw-name lookup silently empties mass_balance.
    name = "nancon_intermittence_mf6"
    listing = _listing_path(Path("/out"), name)

    assert listing.stem == mf6_safe_name(name)
    assert listing.stem != name
    assert len(listing.stem) <= 16


def test_already_safe_name_is_left_alone() -> None:
    # Windows paths hand the extractor the safe name directly: no double hash.
    safe = mf6_safe_name("nancon_intermittence_mf6")

    assert _listing_path(Path("/out"), safe).stem == safe


def test_spaced_name_listing_matches_the_sanitised_model_name() -> None:
    assert _listing_path(Path("/out"), "run one").stem == "run_one"
