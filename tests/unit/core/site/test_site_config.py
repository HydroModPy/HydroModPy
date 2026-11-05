"""The [site] section: the name grammar and the URI form are refused by name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.core.site import SiteConfig


@pytest.mark.parametrize("name", ["nancon", "J0014010", "le_nancon_2", "A_b_9"])
def test_a_site_name_is_letters_digits_and_underscores(name: str) -> None:
    assert SiteConfig(name=name).name == name


@pytest.mark.parametrize("name", ["", "le-nancon", "nancon.v2", "le nancon", "nançon", "a/b"])
def test_a_site_name_with_another_character_is_refused(name: str) -> None:
    with pytest.raises(ValidationError, match="name"):
        SiteConfig(name=name)


@pytest.mark.parametrize("uri", ["hubeau:J0014010", "bdtopage:J001-0000", "hubeau:a_b"])
def test_a_registry_uri_is_accepted(uri: str) -> None:
    assert SiteConfig(name="nancon", uri=uri).uri == uri


@pytest.mark.parametrize("uri", ["J0014010", "sandre:J0014010", "hubeau:", "hubeau:J00 14"])
def test_a_uri_outside_the_two_registries_is_refused(uri: str) -> None:
    with pytest.raises(ValidationError, match="uri"):
        SiteConfig(name="nancon", uri=uri)


def test_an_unknown_site_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="station"):
        SiteConfig(name="nancon", station="J0014010")


def test_the_name_is_required() -> None:
    with pytest.raises(ValidationError, match="name"):
        SiteConfig(label="Le Nançon")
