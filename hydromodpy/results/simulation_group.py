from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.simulation import Simulation


class SimulationGroup:

    def __init__(
        self,
        sim_ids: list[str],
        catalog: SimulationCatalog,
    ) -> None:
        self._sim_ids = sim_ids
        self._catalog = catalog

    @property
    def count(self) -> int:
        return len(self._sim_ids)

    @property
    def sim_ids(self) -> list[str]:
        return list(self._sim_ids)

    def __len__(self) -> int:
        return len(self._sim_ids)

    def __iter__(self):
        from hydromodpy.results.simulation import Simulation

        for sid in self._sim_ids:
            yield Simulation(sid, self._catalog)

    def __getitem__(self, index: int) -> Simulation:
        from hydromodpy.results.simulation import Simulation

        return Simulation(self._sim_ids[index], self._catalog)

    # -- Pivot DataFrames ----------------------------------------------------

    @property
    def parameters(self) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog.connection.execute(
            f"SELECT sim_id, param_name, zone_id, value "
            f"FROM parameters WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["key"] = df["param_name"].where(
            df["zone_id"] == "_homogeneous",
            df["param_name"] + "_" + df["zone_id"],
        )
        return df.pivot_table(
            index="sim_id", columns="key", values="value", aggfunc="first",
        ).reset_index()

    @property
    def metrics(self) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog.connection.execute(
            f"SELECT sim_id, station_id, metric_name, value "
            f"FROM metrics WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["key"] = df["metric_name"].where(
            df["station_id"].isna(),
            df["metric_name"] + "_" + df["station_id"],
        )
        return df.pivot_table(
            index="sim_id", columns="key", values="value", aggfunc="first",
        ).reset_index()

    # -- Comparison ----------------------------------------------------------

    def compare(self, metric: str) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        return self._catalog.connection.execute(
            f"SELECT s.sim_id, s.name, s.project, s.solver, m.station_id, m.value "
            f"FROM simulations s "
            f"JOIN metrics m ON s.sim_id = m.sim_id "
            f"WHERE s.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value DESC",
            self._sim_ids + [metric],
        ).fetchdf()

    def best(self, metric: str) -> Simulation:
        from hydromodpy.results.simulation import Simulation

        if not self._sim_ids:
            raise ValueError("Empty group")
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        row = self._catalog.connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value DESC LIMIT 1",
            self._sim_ids + [metric],
        ).fetchone()
        if row is None:
            raise KeyError(f"No metric '{metric}' found in group")
        return Simulation(str(row[0]), self._catalog)

    def worst(self, metric: str) -> Simulation:
        from hydromodpy.results.simulation import Simulation

        if not self._sim_ids:
            raise ValueError("Empty group")
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        row = self._catalog.connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value ASC LIMIT 1",
            self._sim_ids + [metric],
        ).fetchone()
        if row is None:
            raise KeyError(f"No metric '{metric}' found in group")
        return Simulation(str(row[0]), self._catalog)

    def sort_by(self, metric: str, ascending: bool = True) -> SimulationGroup:
        if not self._sim_ids:
            return self
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        order = "ASC" if ascending else "DESC"
        rows = self._catalog.connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value {order}",
            self._sim_ids + [metric],
        ).fetchall()
        sorted_ids = [str(r[0]) for r in rows]
        return SimulationGroup(sorted_ids, self._catalog)

    # -- ML-ready export -----------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        sims = self._catalog.connection.execute(
            f"SELECT sim_id, project, solver, solver_category, flow_regime, "
            f"n_cells, n_layers "
            f"FROM simulations WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()

        params = self.parameters
        metrics = self.metrics

        df = sims
        if not params.empty:
            df = df.merge(params, on="sim_id", how="left")
        if not metrics.empty:
            df = df.merge(metrics, on="sim_id", how="left")
        return df

    def to_csv(self, path: Path | str) -> None:
        self.to_dataframe().to_csv(str(path), index=False)

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SimulationGroup(count={self.count})"
