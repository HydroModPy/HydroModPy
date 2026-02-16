"""Test de non-regression end-to-end pour example_00.py.

Objectif principal:
- executer le vrai workflow HydroModPy (et pas un mock),
- extraire des signatures numeriques compactes sur les sorties,
- comparer ces signatures a des references "golden".

Pourquoi ce design:
- on evite de comparer des fichiers binaires complets (trop fragile),
- on garde une verification scientifique utile (stats derivees),
- on detecte les regressions de comportement sans surcontraindre le format.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


# REPO_ROOT:
# Point d'entree absolu du depot. Utilise pour:
# - localiser example_00.py
# - localiser les executables bin/* (MODFLOW/MODPATH)
# - lancer le script dans le bon working directory
REPO_ROOT = Path(__file__).resolve().parents[2]

# EXAMPLE_00_SCRIPT:
# Script de reference execute pendant le test.
# Le test doit couvrir ce script complet car il represente le workflow utilisateur.
EXAMPLE_00_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "00_quick_test_of_wide_hydromodpy_capabilities"
    / "example_00.py"
)

# GOLDEN_REFERENCE_FILE:
# Fichier JSON versionne contenant les valeurs attendues.
# Ces valeurs servent de baseline de non-regression.
GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_00_npy_signatures.json"
)

# Chargement unique des references au chargement du module de test.
with GOLDEN_REFERENCE_FILE.open("r", encoding="utf-8") as stream:
    GOLDEN_REFERENCES = json.load(stream)

# Deux sous-ensembles logiques:
# - MODFLOW_EXPECTED: signatures derivees des .npy MODFLOW
# - MODPATH_EXPECTED: signatures derivees des snapshots MODPATH
MODFLOW_EXPECTED = GOLDEN_REFERENCES["modflow_expected"]
MODPATH_EXPECTED = GOLDEN_REFERENCES["modpath_expected"]


def _load_npy_dict(path: Path):
    """Charge un .npy qui contient un dict Python."""
    # Les sorties HydroModPy sont historisees en .npy pickles (dict de matrices).
    # Le test consomme ce format tel quel.
    return np.load(path, allow_pickle=True).item()


def _array_stats(values):
    """Calcule des stats stables en ignorant les NaN."""
    # Conversion defensive en float pour homogeniser les calculs.
    arr = np.asarray(values, dtype=float)
    # On isole uniquement les valeurs finies:
    # cela neutralise NaN/+inf/-inf eventuels.
    finite = arr[np.isfinite(arr)]

    # Signature "vide" explicite si aucune valeur exploitable.
    if finite.size == 0:
        return {"count": 0, "mean": None, "p50": None, "p95": None}

    # On renvoie des indicateurs robustes:
    # - count: volume de donnees validees
    # - mean: tendance globale
    # - p50/p95: niveau median et borne haute
    return {
        "count": int(finite.size),
        "mean": float(finite.mean()),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
    }


def _assert_stats(actual, expected):
    """Compare les stats avec tolerances numeriques."""
    # Le nombre de points valides doit etre strictement identique.
    assert actual["count"] == expected["count"]

    # Les floats peuvent varier legerement selon plateforme/libs.
    # On autorise donc une faible tolerance (approx) sur mean/p50/p95.
    for key in ("mean", "p50", "p95"):
        if expected[key] is None:
            assert actual[key] is None
        else:
            assert actual[key] == pytest.approx(expected[key], rel=1e-4, abs=1e-6)


def _modflow_signature(path: Path):
    """Construit une signature compacte MODFLOW sur le dernier timestep."""
    # data: dict {timestep_index -> matrice 2D}
    data = _load_npy_dict(path)

    # Le fichier doit contenir au moins un pas de temps.
    assert len(data) > 0

    # Choix explicite: on valide le dernier pas de temps.
    # Cela couvre l'etat final de la simulation.
    last_timestep = sorted(data.keys())[-1]
    arr = np.asarray(data[last_timestep], dtype=float)

    # Signature numerique compacte de la matrice choisie.
    sig = _array_stats(arr)
    sig["shape"] = list(arr.shape)
    sig["timestep"] = int(last_timestep)
    sig["available_timesteps"] = len(data)

    # Somme globale: indicateur additif utile pour capter des ecarts diffus.
    if sig["count"] == 0:
        sig["sum"] = None
    else:
        finite = arr[np.isfinite(arr)]
        sig["sum"] = float(finite.sum())
    return sig


def _snapshot_signature(path: Path):
    """Construit une signature compacte d'un snapshot MODPATH."""
    # Snapshot genere dans hydromodpy/modeling/modpath.py.
    # Le format est deja "compact", mais on derive encore des stats
    # sur time/time_win/rchPerc pour comparaison robuste.
    snapshot = _load_npy_dict(path)
    return {
        # Metadonnees de contexte
        "source": snapshot["source"],
        "track_dir": snapshot["track_dir"],
        "n_starting": int(snapshot["n_starting"]),
        "n_ending": int(snapshot["n_ending"]),
        "n_particles": int(snapshot["n_particles"]),
        # Signatures numeriques comparees au golden JSON
        "time": _array_stats(snapshot["time"]),
        "time_win": _array_stats(snapshot["time_win"]),
        "rchPerc": _array_stats(snapshot["rchPerc"]),
    }


def _assert_required_executables():
    """Skip si les executables MODFLOW/MODPATH ne sont pas disponibles."""
    # Selection des executables selon OS.
    # Le test doit rester portable: skip propre si environnement non supporte.
    if platform.system() == "Windows":
        mf_exe = REPO_ROOT / "bin" / "win" / "mfnwt.exe"
        mp_exe = REPO_ROOT / "bin" / "win" / "mp6.exe"
    elif platform.system() == "Linux":
        mf_exe = REPO_ROOT / "bin" / "linux" / "mfnwt"
        mp_exe = REPO_ROOT / "bin" / "linux" / "mp6"
    elif platform.system() == "Darwin":
        mf_exe = REPO_ROOT / "bin" / "mac" / "mfnwt"
        mp_exe = REPO_ROOT / "bin" / "mac" / "mp6"
    else:
        pytest.skip(f"Unsupported platform for bundled executables: {platform.system()}")

    # Si binaire manquant, on skip plutot que d'echouer faussement le code.
    missing = [str(p) for p in (mf_exe, mp_exe) if not p.exists()]
    if missing:
        pytest.skip(f"Required executables are missing: {missing}")


def _run_example_00_script(out_path: Path):
    """Execute example_00.py et echoue avec logs complets en cas de crash."""
    # Copie de l'environnement courant pour garder les activations conda, etc.
    env = os.environ.copy()

    # Redirige les sorties de l'exemple dans un dossier temporaire pytest.
    # Cela evite toute pollution du dossier examples/results du repo.
    env["HYDROMODPY_EXAMPLE00_OUT_PATH"] = str(out_path)

    # Desactive les sections de plot pour un run headless stable en CI.
    env["HYDROMODPY_EXAMPLE00_SKIP_PLOTS"] = "1"

    # Force un backend non interactif pour matplotlib.
    env.setdefault("MPLBACKEND", "Agg")

    # C'est ici que le script utilisateur reel est execute.
    command = [sys.executable, str(EXAMPLE_00_SCRIPT)]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=1200,
    )

    # En cas d'echec, on remonte stdout/stderr complets
    # pour faciliter le diagnostic.
    assert completed.returncode == 0, (
        "example_00.py failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )


@pytest.mark.regression
@pytest.mark.slow
def test_example_00_regression_on_npy_outputs(tmp_path):
    # 1) Guard: ensure required external binaries are present.
    _assert_required_executables()

    # 2) Run the full example workflow in an isolated output folder.
    out_path = tmp_path / "example_00_outputs"
    _run_example_00_script(out_path)

    # 3) Resolve output folders generated by the example run.
    model_ws = out_path / "Example_00_Aber" / "results_simulations" / "reg_0"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"

    # 4) Validate MODFLOW signatures derived from generated .npy files.
    for name, expected in MODFLOW_EXPECTED.items():
        # Signature calculee sur le dernier pas de temps.
        actual = _modflow_signature(postprocess_dir / f"{name}.npy")

        # Controle structurel minimal avant comparaison numerique.
        assert actual["shape"] == expected["shape"]
        if "timestep" in expected:
            assert actual["timestep"] == expected["timestep"]
        if "available_timesteps" in expected:
            assert actual["available_timesteps"] == expected["available_timesteps"]

        # Controle des stats derivees.
        _assert_stats(actual, expected)

        # La somme est verifiee a part car elle n'appartient pas a _assert_stats.
        if expected["sum"] is None:
            assert actual["sum"] is None
        else:
            assert actual["sum"] == pytest.approx(expected["sum"], rel=1e-4, abs=1e-6)

    # 5) Validate MODPATH signatures derived from generated snapshot .npy files.
    for filename, expected in MODPATH_EXPECTED.items():
        # Lecture + reduction du snapshot en signature comparable.
        actual = _snapshot_signature(particles_dir / filename)

        # Metadonnees de contexte (doivent etre exactes).
        assert actual["source"] == expected["source"]
        assert actual["track_dir"] == expected["track_dir"]
        assert actual["n_starting"] == expected["n_starting"]
        assert actual["n_ending"] == expected["n_ending"]
        assert actual["n_particles"] == expected["n_particles"]

        # Stats sur les series temporelles particulaires.
        _assert_stats(actual["time"], expected["time"])
        _assert_stats(actual["time_win"], expected["time_win"])
        _assert_stats(actual["rchPerc"], expected["rchPerc"])
