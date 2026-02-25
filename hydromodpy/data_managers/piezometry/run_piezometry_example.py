"""Run an end-to-end piezometry station-set example.

This script reads the local ``piezometry_config.toml`` file, builds a
``PiezometerSet``, prints a completeness report, and exports one plot
per station.
"""

from pathlib import Path

try:
    from ..common.utils import safe_file_token
    from .piezometer_set import PiezometerSet
except ImportError:
    try:
        from common.utils import safe_file_token
    except ImportError:
        from hydromodpy.data_managers.common.utils import safe_file_token
    from piezometer_set import PiezometerSet


DISCOVERY_BBOX = (2.90, 45.84, 3.46, 46.33)
FALLBACK_IDS = ["06932X0178/P10", "06216X0228/P30-10"]


def _fmt_date_or_none(value):
    """Return ``YYYY-MM-DD`` string or ``None``."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%d")


def _safe_id_token(value: str) -> str:
    """Return a filesystem-safe token for one piezometer id."""
    return safe_file_token(value)


def main() -> None:
    """Execute the piezometry example workflow."""
    manager_dir = Path(__file__).resolve().parent
    config_path = manager_dir / "piezometry_config.toml"
    outputs_dir = manager_dir / "outputs"

    piezometers = PiezometerSet.from_toml(config_path)
    if not piezometers.piezometers:
        print("No loaded piezometer data from configured IDs.")
        print(f"Trying automatic discovery in bbox={DISCOVERY_BBOX}...")
        start = _fmt_date_or_none(piezometers.date_start)
        end = _fmt_date_or_none(piezometers.date_end)
        discovered = PiezometerSet.discover_piezometer_ids(
            bbox=DISCOVERY_BBOX,
            require_observations=True,
            date_start=start,
            date_end=end,
            max_ids=6,
            timeout=60,
        )
        if len(discovered) < 2:
            print(
                "Automatic discovery returned fewer than 2 IDs; "
                "using known fallback IDs."
            )
            discovered = FALLBACK_IDS
        else:
            print(f"Discovered IDs: {discovered[:6]}")

        piezometers = PiezometerSet(
            measurement=piezometers.measurement,
            id=discovered[:2],
            display=piezometers.display,
            date_start=start,
            date_end=end,
            output=piezometers.output,
            source_mode="api",
        )

    piezometers.get_completeness_report()
    if not piezometers.piezometers:
        print("No loaded piezometer data available; skipping plot export.")
        print(
            "Tip: use PiezometerSet.discover_piezometer_ids("
            "bbox=(minx, miny, maxx, maxy), require_observations=True)"
        )
        return
    station_ids = sorted(piezometers.piezometers.keys())
    for station_id in station_ids:
        output_path = outputs_dir / f"piezometer_plot_{_safe_id_token(station_id)}.png"
        piezometers.plot_piezometer(
            piezometer_id=station_id,
            output_path=output_path,
            show=True,
        )


if __name__ == "__main__":
    main()
