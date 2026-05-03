"""Run the external comparison workflow and optionally display generated figures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher

DEFAULT_CONFIG = Path(__file__).with_name("compare_dupuit_mf6_bouss.toml")
NATURAL_CONFIG = Path(__file__).with_name("compare_vire_natural_mf6_nwt.toml")
NATURAL_BOUSS_CONFIG = Path(__file__).with_name("compare_10km2_natural_mesh_mf6_bouss.toml")
NATURAL_BOUSS_RECHARGE_CONFIG = Path(__file__).with_name(
    "compare_10km2_natural_mesh_recharge_mf6_bouss.toml"
)
NATURAL_BOUSS_TRANSIENT_PULSE_CONFIG = Path(__file__).with_name(
    "compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml"
)
NANCON_SEASONAL_CONFIG = Path(__file__).with_name(
    "compare_nancon_transient_seasonal_mf6_bouss.toml"
)
NANCON_SEASONAL_HYDROGRAPHY_CONFIG = Path(__file__).with_name(
    "compare_nancon_transient_seasonal_hydrography_mf6_bouss.toml"
)
CONFIG_BY_CASE = {
    "synthetic": DEFAULT_CONFIG,
    "natural": NATURAL_CONFIG,
    "natural-bouss": NATURAL_BOUSS_CONFIG,
    "natural-bouss-recharge": NATURAL_BOUSS_RECHARGE_CONFIG,
    "natural-bouss-transient-pulse": NATURAL_BOUSS_TRANSIENT_PULSE_CONFIG,
    "nancon-seasonal": NANCON_SEASONAL_CONFIG,
    "nancon-seasonal-hydrography": NANCON_SEASONAL_HYDROGRAPHY_CONFIG,
}


def _print_summary(manifest: dict) -> None:
    print(f"Comparison id: {manifest.get('comparison_id', '')}")
    print(f"Audit status : {manifest.get('audit_status', '')}")
    print(f"Output root  : {manifest.get('comparison_root', '')}")
    print(f"Report       : {manifest.get('comparison_report_md', '')}")
    print(f"Manifest     : {manifest.get('manifest_path', '')}")
    print("Figures:")
    for item in manifest.get("comparison_figures", []):
        print(f"  - {item.get('kind', '')}: {item.get('path', '')}")


def _show_figures(manifest: dict, *, limit: int) -> None:
    figure_paths = [
        Path(str(item.get("path", "")))
        for item in manifest.get("comparison_figures", [])
        if str(item.get("path", "")).lower().endswith(".png")
    ]
    figure_paths = [path for path in figure_paths if path.exists()]
    if not figure_paths:
        print("No PNG figure found to display.")
        return

    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    selected = figure_paths[: max(1, limit)]
    figure, axes = plt.subplots(len(selected), 1, figsize=(11, 4.5 * len(selected)))
    if len(selected) == 1:
        axes = [axes]
    for ax, path in zip(axes, selected, strict=False):
        ax.imshow(mpimg.imread(path))
        ax.set_title(path.name)
        ax.axis("off")
    figure.tight_layout()
    plt.show()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Comparison TOML to run.",
    )
    parser.add_argument(
        "--case",
        choices=tuple(CONFIG_BY_CASE) + ("all",),
        default=None,
        help="Named example case to run.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the generated PNG figures after the comparison run.",
    )
    parser.add_argument(
        "--show-limit",
        type=int,
        default=4,
        help="Maximum number of generated PNG figures to display.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full comparison manifest as JSON.",
    )
    args = parser.parse_args(argv)

    if args.config is not None and args.case is not None:
        parser.error("provide either a positional config or --case, not both")

    if args.case == "all":
        config_paths = list(CONFIG_BY_CASE.values())
    elif args.case is not None:
        config_paths = [CONFIG_BY_CASE[args.case]]
    else:
        config_paths = [args.config or DEFAULT_CONFIG]

    manifests = []
    for index, config_path in enumerate(config_paths):
        if len(config_paths) > 1 and not args.print_json:
            if index:
                print()
            print(f"=== {config_path.name} ===")
        manifest = SimulationComparisonLauncher(config_path).run()
        manifests.append(manifest)

    if args.print_json:
        payload = manifests[0] if len(manifests) == 1 else manifests
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        for index, manifest in enumerate(manifests):
            if index:
                print()
            _print_summary(manifest)
    if args.show:
        for manifest in manifests:
            _show_figures(manifest, limit=args.show_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
