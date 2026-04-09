#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash install/enter_wsl_dev.sh [options] [-- command...]

Open one ready-to-use HydroModPy WSL shell, or run one command inside it.

Options:
  --env-name NAME      Conda environment name (default: hydromodpy-wsl)
  --headless           Export HYDROMODPY_NO_DISPLAY=1 and MPLBACKEND=Agg
  --with-display       Unset HYDROMODPY_NO_DISPLAY and MPLBACKEND
  --output-root PATH   Export HYDROMODPY_OUT_PATH to the given path
  -h, --help           Show this help and exit

Examples:
  bash install/enter_wsl_dev.sh
  bash install/enter_wsl_dev.sh --headless
  bash install/enter_wsl_dev.sh --output-root /mnt/c/Users/dreuzy/Documents/HydroModPyOutputs
  bash install/enter_wsl_dev.sh -- python -m pytest tests/unit/simulation/test_boussinesq_flow_adapter.py -q
EOF
}

ENV_NAME="hydromodpy-wsl"
HEADLESS_MODE="keep"
OUTPUT_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name)
      ENV_NAME="$2"
      shift 2
      ;;
    --headless)
      HEADLESS_MODE="on"
      shift
      ;;
    --with-display)
      HEADLESS_MODE="off"
      shift
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

resolve_env_target() {
  local env_name="$1"

  if conda env list 2>/dev/null | awk '{print $1}' | grep -Fxq "${env_name}"; then
    printf '%s\n' "${env_name}"
    return 0
  fi

  local candidates=(
    "${HOME}/miniforge3/envs/${env_name}"
    "${HOME}/mambaforge/envs/${env_name}"
    "${HOME}/miniconda3/envs/${env_name}"
    "${HOME}/anaconda3/envs/${env_name}"
  )

  local candidate=""
  for candidate in "${candidates[@]}"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

load_conda() {
  if command -v conda >/dev/null 2>&1; then
    if [[ "$(type -t conda || true)" == "function" ]]; then
      return 0
    fi

    local conda_base=""
    if conda_base="$(conda info --base 2>/dev/null)"; then
      if [[ -f "${conda_base}/etc/profile.d/conda.sh" ]]; then
        # shellcheck disable=SC1090
        source "${conda_base}/etc/profile.d/conda.sh"
        if [[ "$(type -t conda || true)" == "function" ]]; then
          return 0
        fi
      fi
    fi

    if eval "$(conda shell.bash hook 2>/dev/null)"; then
      if [[ "$(type -t conda || true)" == "function" ]]; then
        return 0
      fi
    fi
  fi

  local candidates=(
    "${HOME}/miniforge3/etc/profile.d/conda.sh"
    "${HOME}/mambaforge/etc/profile.d/conda.sh"
    "${HOME}/anaconda3/etc/profile.d/conda.sh"
    "${HOME}/miniconda3/etc/profile.d/conda.sh"
  )

  local candidate=""
  for candidate in "${candidates[@]}"; do
    if [[ -f "${candidate}" ]]; then
      # shellcheck disable=SC1090
      source "${candidate}"
      return 0
    fi
  done

  echo "conda could not be found in this WSL shell." >&2
  echo "Run: bash install/setup_wsl_dev.sh --env-name ${ENV_NAME} --with-petsc" >&2
  exit 1
}

load_conda
if ! ENV_TARGET="$(resolve_env_target "${ENV_NAME}")"; then
  echo "Could not find Conda environment '${ENV_NAME}'." >&2
  echo "Known locations checked: ~/miniforge3/envs, ~/mambaforge/envs, ~/miniconda3/envs, ~/anaconda3/envs" >&2
  echo "If needed, create it once with:" >&2
  echo "  bash install/setup_wsl_dev.sh --env-name ${ENV_NAME} --with-petsc" >&2
  exit 1
fi

conda activate "${ENV_TARGET}"
cd "${REPO_ROOT}"

case "${HEADLESS_MODE}" in
  on)
    export HYDROMODPY_NO_DISPLAY=1
    export MPLBACKEND=Agg
    ;;
  off)
    unset HYDROMODPY_NO_DISPLAY || true
    unset MPLBACKEND || true
    ;;
esac

if [[ -n "${OUTPUT_ROOT}" ]]; then
  export HYDROMODPY_OUT_PATH="${OUTPUT_ROOT}"
fi

echo "HydroModPy WSL session ready"
echo "  repo: ${REPO_ROOT}"
echo "  env:  ${ENV_TARGET}"
if [[ -n "${OUTPUT_ROOT}" ]]; then
  echo "  out:  ${HYDROMODPY_OUT_PATH}"
fi

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

exec "${SHELL:-/bin/bash}" -i
