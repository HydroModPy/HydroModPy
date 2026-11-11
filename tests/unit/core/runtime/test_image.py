"""The image tag and digest of the process, read from two variables."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.runtime.image import DIGEST_FORM, image_of

DIGEST = "sha256:" + "ab12" * 16


@pytest.mark.parametrize(
    ("tag", "digest", "expected"),
    [
        (None, None, {}),
        (None, DIGEST, {}),
        ("", DIGEST, {}),
        ("2.1.0", None, {"tag": "2.1.0"}),
        ("2.1.0", "", {"tag": "2.1.0"}),
        ("2.1.0", DIGEST, {"tag": "2.1.0", "digest": DIGEST}),
        ("  dev ", f" {DIGEST} ", {"tag": "dev", "digest": DIGEST}),
    ],
)
def test_image_of(monkeypatch, tag, digest, expected) -> None:
    for name, value in (("HMP_IMAGE_TAG", tag), ("HMP_IMAGE_DIGEST", digest)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    assert image_of() == expected


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
