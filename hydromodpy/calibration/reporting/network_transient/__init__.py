"""Diagnostic HTML pages for transient network calibration runs.

This package backs the ``network_transient_html.py`` facade with four concerns:

- ``state``: mutable defaults loaded from ``validation_cases/calibration/network_transient_b0/fixture.toml``.
- ``io``: CSV/JSON/TOML readers, artifact inspection and small parsing helpers.
- ``args``: runtime configuration of the report globals.
- ``blocks``: report blocks rendered through the shared ``display.report_blocks`` engine.

The companion module ``network_transient_html.py`` is the public facade.
"""

from __future__ import annotations
