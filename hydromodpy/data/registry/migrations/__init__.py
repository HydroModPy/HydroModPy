"""Data cache DuckDB schema migrations.

``runner.py`` applies the bundled ``<NNNN>_<slug>.sql`` scripts of this folder
and keeps the ledger of the data cache. ``auto_boot.py`` adds the file lock and
the pre-migration backup, and ``errors.py`` holds the typed failures. Import
from the module that holds the name.
"""
