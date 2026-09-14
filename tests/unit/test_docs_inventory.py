from __future__ import annotations

from tools import check_docs_inventory


def test_cli_reference_matches_registered_commands() -> None:
    assert check_docs_inventory.check_cli_reference() == []


def test_authored_docs_do_not_reference_removed_paths_or_commands() -> None:
    assert check_docs_inventory.check_banned_authored_references() == []


def test_api_reference_lists_required_public_api_pages() -> None:
    assert check_docs_inventory.check_api_reference_pages() == []


def test_user_guide_lists_required_topic_pages() -> None:
    assert check_docs_inventory.check_user_guide_pages() == []


def test_authored_user_guide_pages_link_somewhere() -> None:
    assert check_docs_inventory.check_user_guide_crossrefs() == []


def test_data_family_pages_follow_the_shared_template() -> None:
    assert check_docs_inventory.check_data_pages_follow_template() == []


def test_api_reference_never_recurses() -> None:
    assert check_docs_inventory.check_api_reference_is_not_recursive() == []
