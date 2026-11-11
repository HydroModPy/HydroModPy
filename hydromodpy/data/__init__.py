"""Public API for HydroModPy data loading and planning.

This package-level facade stays lazy so doc builds and lightweight imports do
not instantiate the full data-manager dependency graph. A name resolved here is
cached in this module: a test that replaces one patches ``hydromodpy.data.<Name>``,
not the module that defines it.
"""
