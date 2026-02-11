from __future__ import annotations

import logging

from .main import run_common


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_common()


if __name__ == "__main__":
    main()
