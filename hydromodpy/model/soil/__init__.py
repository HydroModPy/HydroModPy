"""Daily soil reservoir that turns precipitation and ETP into recharge.

MODFLOW 6 only. See ``kernel.py`` for the equations and ``config.py`` for the
TOML surface. ``grids.py``, ``columns.py``, ``recharge.py`` and ``budget.py``
run the reservoir on the SAFRAN grids a project loads. This file has no
imports on purpose, so each module reads on its own.
"""
