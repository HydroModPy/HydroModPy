"""HMAC-signed pickle helpers.

Plain ``pickle.load`` on attacker-controlled bytes allows arbitrary code
execution. The functions below wrap a pickle blob with an HMAC-SHA256 tag
keyed by a per-workspace secret. ``loads_signed`` rejects payloads whose
tag does not verify, so an attacker who cannot read the key cannot forge
a payload that survives :func:`pickle.loads`.

Format on disk
--------------

::

    <32-byte HMAC-SHA256 tag><pickle blob>

The tag is computed over the pickle blob with the workspace key.
"""

from __future__ import annotations

import hmac
import os
import pickle
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Any

_TAG_LEN = sha256().digest_size
_KEY_LEN = 32


class SignatureError(Exception):
    """Raised when a signed pickle blob fails HMAC verification."""


def dumps_signed(obj: Any, key: bytes) -> bytes:
    """Pickle ``obj`` and prefix the result with an HMAC-SHA256 tag."""
    if len(key) < _KEY_LEN:
        raise ValueError(f"signing key must be at least {_KEY_LEN} bytes")
    blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    tag = hmac.new(key, blob, sha256).digest()
    return tag + blob


def loads_signed(payload: bytes, key: bytes) -> Any:
    """Verify the HMAC tag of ``payload`` and unpickle the body.

    Raises :class:`SignatureError` if the tag is missing, malformed, or
    does not match the expected HMAC for ``key``. The pickle body is only
    deserialized after verification succeeds.
    """
    if len(payload) < _TAG_LEN:
        raise SignatureError("signed pickle blob is shorter than the HMAC tag")
    tag, blob = payload[:_TAG_LEN], payload[_TAG_LEN:]
    expected = hmac.new(key, blob, sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise SignatureError("signed pickle blob failed HMAC verification")
    return pickle.loads(blob)


def load_or_create_key(key_path: Path) -> bytes:
    """Return the signing key at ``key_path``, creating it on first call.

    The key is a 32-byte secret. Parent directories are created on
    demand. When the file is created, POSIX permissions are tightened to
    ``0o600`` so other local users cannot read it.
    """
    key_path = Path(key_path)
    if key_path.exists():
        data = key_path.read_bytes()
        if len(data) < _KEY_LEN:
            raise SignatureError(f"signing key at {key_path} is too short")
        return data
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_KEY_LEN)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


__all__ = (
    "SignatureError",
    "dumps_signed",
    "load_or_create_key",
    "loads_signed",
)
