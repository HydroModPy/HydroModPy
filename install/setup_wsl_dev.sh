#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash install/setup_wsl_dev.sh [options]

Create or update a Linux/WSL developer environment for HydroModPy.

Options:
  --env-name NAME   Conda environment name (default: hydromodpy-wsl)
  --full            Use the full editable stack with Spyder/Jupyter extras
  --with-petsc      Install PETSc, petsc4py, mpi4py, and mpich in the env
  --skip-apt        Do not install Ubuntu system dependencies with apt
  -h, --help        Show this help and exit

Examples:
  bash install/setup_wsl_dev.sh
  bash install/setup_wsl_dev.sh --env-name hydromodpy-linux --with-petsc
  bash install/setup_wsl_dev.sh --full
EOF
}

ENV_NAME="hydromodpy-wsl"
ENV_FILE="env_hydromodpy_light_pkg.yml"
WITH_PETSC=0
USE_APT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name)
      ENV_NAME="$2"
      shift 2
      ;;
    --full)
      ENV_FILE="env_hydromodpy_pkg.yml"
      shift
      ;;
    --with-petsc)
      WITH_PETSC=1
      shift
      ;;
    --skip-apt)
      USE_APT=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${SCRIPT_DIR}/${ENV_FILE}" ]]; then
  echo "Environment file not found: ${SCRIPT_DIR}/${ENV_FILE}" >&2
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  cat >&2 <<'EOF'
conda was not found in this shell.

Install Miniforge inside WSL first, for example:
  sudo apt update && sudo apt install -y curl
  curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
  bash Miniforge3-Linux-x86_64.sh
  source ~/miniforge3/etc/profile.d/conda.sh
EOF
  exit 1
fi

if [[ "${USE_APT}" -eq 1 ]] && command -v apt-get >/dev/null 2>&1; then
  APT_PREFIX=""
  if command -v sudo >/dev/null 2>&1; then
    APT_PREFIX="sudo"
  fi
  ${APT_PREFIX} apt-get update
  ${APT_PREFIX} apt-get install -y libglu1-mesa libxft2
fi

pushd "${SCRIPT_DIR}" >/dev/null
if ! conda env create -n "${ENV_NAME}" -f "${ENV_FILE}"; then
  conda env update -n "${ENV_NAME}" -f "${ENV_FILE}" --prune
fi
popd >/dev/null

if [[ "${WITH_PETSC}" -eq 1 ]]; then
  conda install -n "${ENV_NAME}" -c conda-forge -y petsc petsc4py mpi4py mpich
  conda run -n "${ENV_NAME}" python -c "from petsc4py import PETSc; print('PETSc', PETSc.Sys.getVersion())"
fi

conda run -n "${ENV_NAME}" python -c "import hydromodpy; print('HydroModPy', hydromodpy.__version__)"

cat <<EOF

Environment ready: ${ENV_NAME}
Repository root:   ${REPO_ROOT}

Suggested next commands:
  conda activate ${ENV_NAME}
  export HYDROMODPY_NO_DISPLAY=1
  export MPLBACKEND=Agg
  python -m pytest tests/unit -q
  hmp test regression --fast -j 2
  hmp test validation --fast
EOF
