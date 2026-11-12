"""The image tag and digest of the process, read from two variables."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.runtime.image import DIGEST_FORM, image_of

DIGEST = "sha256:" + "ab12" * 16


@pytest.mark.parametrize(
    "digest",
    [
        "abc",
        "sha256:" + "ab" * 31,
        "sha256:" + "AB12" * 16,
        "sha512:" + "ab12" * 16,
        "sha256:" + "zz12" * 16,
        "sha256:" + "ab12" * 17,
    ],
)
def test_a_malformed_digest_is_refused_with_the_form(monkeypatch, digest) -> None:
    monkeypatch.setenv("HMP_IMAGE_TAG", "2.1.0")
    monkeypatch.setenv("HMP_IMAGE_DIGEST", digest)

    with pytest.raises(ConfigError, match="sha256:<64 lowercase hex") as caught:
        image_of()

    assert DIGEST_FORM in str(caught.value)
    assert image_of(refuse=False) == {"tag": "2.1.0", "digest_refused": digest.strip()}
