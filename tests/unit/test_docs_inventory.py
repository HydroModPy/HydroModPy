from __future__ import annotations

from tools import check_docs_inventory


def test_cli_reference_matches_registered_commands() -> None:
    assert check_docs_inventory.check_cli_reference() == []


def test_authored_docs_do_not_reference_removed_paths_or_commands() -> None:
    assert check_docs_inventory.check_banned_authored_references() == []


def test_api_reference_lists_required_public_api_pages() -> None:
    assert check_docs_inventory.check_api_reference_pages() == []
