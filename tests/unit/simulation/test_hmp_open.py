from __future__ import annotations

from hydromodpy.results.catalog import Catalog


class TestHmpOpen:
    def test_open_returns_catalog(self, tmp_path):
        import hydromodpy as hmp

        cat = hmp.open(tmp_path / "ws", create=True)
        assert isinstance(cat, Catalog)
        cat.close()

    def test_open_roundtrip(self, tmp_path):
        import hydromodpy as hmp

        with hmp.open(tmp_path / "ws", create=True) as cat:
            cat.register_simulation(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "test",
                "modflow6",
            )
        with hmp.open(tmp_path / "ws", create=True) as cat:
            df = cat.simulations
            assert len(df) == 1
