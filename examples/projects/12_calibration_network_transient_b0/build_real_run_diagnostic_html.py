"""Build the B0 transient network calibration diagnostic HTML page."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    from validation_cases.calibration.network_transient_b0.network_transient_html import (
        main as report_main,
    )

    report_main()


if __name__ == "__main__":
    main()
