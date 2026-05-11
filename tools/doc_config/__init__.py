"""Documentation pipeline for the HydroModPy configuration reference.

Generates Couche 1 (overview), Couche 2 (per-section pages), and
Couche 4 (annotated TOML reference) under
``docs/source/user_guide/config_reference/``.

Couche 3 (interactive schema explorer) is intentionally out of scope
in v1 and tracked as a Phase 3 evolution.
"""

from tools.doc_config.generate import generate_all

__all__ = ["generate_all"]
