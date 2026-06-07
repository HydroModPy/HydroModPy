"""Reporting layer for HydroModPy.

Hosts HTML composites (calibration session reports, comparison web
reports) and auto-generated Streamlit UI. ``display/`` keeps figure
rendering; ``analysis/`` keeps feature derivation; ``reporting/``
assembles them into multi-figure documents.
"""

from __future__ import annotations
