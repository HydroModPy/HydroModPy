#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="${HYDROMODPY_WSL_PYTHON:-/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" examples/projects/11_nancon_network_physical_benchmark/run_nancon_network_physical_benchmark.py "$@"
