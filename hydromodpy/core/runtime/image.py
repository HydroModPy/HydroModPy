"""The container image a process runs in: its tag and its digest.

This is the one reader of ``HMP_IMAGE_TAG`` and ``HMP_IMAGE_DIGEST``. The
``Dockerfile`` sets the tag. The operator sets the digest when the container
starts, because an image cannot hold its own digest. A run seals both in
``provenance.json``, so a replay in another image can say so.

``image_of()`` returns an empty dict outside a container image. A digest that is not
``sha256:`` followed by 64 hex characters raises ``ConfigError``, which the server does
when it starts. A run calls ``image_of(refuse=False)``, so a bad digest found late is
sealed under ``digest_refused`` and does not stop the run.
"""

from __future__ import annotations

import os
import re

from hydromodpy.core.exceptions import ConfigError

DIGEST_FORM = "sha256:<64 lowercase hex characters>"
"""The form a digest takes, as the refusal writes it."""

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def image_of(*, refuse: bool = True) -> dict[str, str]:
    """Return ``{"tag", "digest"}`` of the image, or ``{}`` outside an image.

    The digest key is left out when ``HMP_IMAGE_DIGEST`` is not set. A digest
    that does not have the form ``sha256:<64 hex>`` raises ``ConfigError``.
    With ``refuse=False`` it goes under ``digest_refused`` instead, so a run
    already under way seals what it was given and does not stop.
    """
    tag = os.environ.get("HMP_IMAGE_TAG", "").strip()
    if not tag:
        return {}
    image = {"tag": tag}
    digest = os.environ.get("HMP_IMAGE_DIGEST", "").strip()
    if digest:
        if _DIGEST.fullmatch(digest):
            image["digest"] = digest
        elif refuse:
            raise ConfigError(f"HMP_IMAGE_DIGEST is {digest!r}, expected {DIGEST_FORM}")
        else:
            image["digest_refused"] = digest
    return image


__all__ = ["DIGEST_FORM", "image_of"]
