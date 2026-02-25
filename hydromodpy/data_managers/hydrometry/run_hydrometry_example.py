"""Run an end-to-end hydrometry station-set example.

This script reads the local ``hydrometry_config.toml`` file, builds a
``StationSet``, prints a completeness report, and exports a plot.
"""

from pathlib import Path

try:
    from .station_set import StationSet
except ImportError:
    from station_set import StationSet


def main() -> None:
    """Execute the hydrometry example workflow."""
    chronicles_dir = Path(__file__).resolve().parent
    config_path = chronicles_dir / "hydrometry_config.toml"
    outputs_dir = chronicles_dir / "outputs"

    stations = StationSet.from_toml(config_path)
    stations.get_completeness_report()
    stations.plot_station(
        output_path=outputs_dir / "station_plot.png",
        show=True,
    )


if __name__ == "__main__":
    main()
