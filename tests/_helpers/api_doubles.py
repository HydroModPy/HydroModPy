"""Reusable context-manager doubles for the functional facade tests.

The ``hmp`` verbs open a ``Project`` as a context manager and forward
kwargs. These doubles record what they receive so a test
can assert the wiring without a real backend. Import them with an absolute
path: ``from tests._helpers.api_doubles import CapturingProject``.
"""

from __future__ import annotations

from typing import Any
