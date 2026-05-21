"""Diagnostic HTML pages for transient network calibration runs.

This package splits the historical ``network_transient_html.py`` module into
five concerns:

- ``state``: mutable defaults loaded from ``validation_cases/calibration/network_transient_b0/fixture.toml``.
- ``io``: CSV/JSON/TOML readers, artifact inspection and small parsing helpers.
- ``charts``: matplotlib figure builders (id card, recharge, outflow maps, ...).
- ``sections``: HTML section builders and metric summaries.
- ``styling``: the CSS string used by the rendered page.
- ``assemble``: the public entry points and the page composition.

The companion module ``network_transient_html.py`` is the public facade.
"""

from __future__ import annotations
