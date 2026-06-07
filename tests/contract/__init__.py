"""Contract tests for CatalogBackend / CacheBackend Protocols.

These tests exercise the Protocol surface independently of the catalog
facade, so a future adapter (Postgres, in-memory, sqlite) can be
validated by re-running the same suite against its concrete class.
"""
