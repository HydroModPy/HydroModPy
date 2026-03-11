"""Runtime helpers shared by validation cases and validation tests."""

from __future__ import annotations

import gc
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from validation_cases.shared.loaders import load_case_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]

_NWT_VALIDATION_PROFILE_SIMPLE = """[modflownwt.runtime]
mf_version = "mfnwt"
mf_listunit = 2
mf_verbose = false
nwt_headtol = 1e-6
nwt_fluxtol = 1e-4
nwt_maxiterout = 500
nwt_thickfact = 1e-5
nwt_linmeth = 1
nwt_iprnwt = 0
nwt_ibotav = 1
nwt_options = "SIMPLE"
nwt_continue = false
nwt_backflag = 0
nwt_stoptol = 1e-10
dis_itmuni = 1
bas_hnoflo = -9999.0
upw_iphdry = 1
upw_hdry = -100.0
upw_layvka = 1
evt_nevtop = 3
evt_ievt = 1
evt_ipakcb = 1
oc_compact = true
wel_ipakcb = 1
lmt_output_file_name = "mt3d_link.ftl"
lmt_extension = "lmt8"
lmt_output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_NWT_VALIDATION_PROFILE_COMPLEX = """[modflownwt.runtime]
mf_version = "mfnwt"
mf_listunit = 2
mf_verbose = false
nwt_headtol = 1e-6
nwt_fluxtol = 1e-4
nwt_maxiterout = 1000
nwt_thickfact = 1e-5
nwt_linmeth = 1
nwt_iprnwt = 0
nwt_ibotav = 1
nwt_options = "COMPLEX"
nwt_continue = false
nwt_backflag = 0
nwt_stoptol = 1e-10
dis_itmuni = 1
bas_hnoflo = -9999.0
upw_iphdry = 1
upw_hdry = -100.0
upw_layvka = 1
evt_nevtop = 3
evt_ievt = 1
evt_ipakcb = 1
oc_compact = true
wel_ipakcb = 1
lmt_output_file_name = "mt3d_link.ftl"
lmt_extension = "lmt8"
lmt_output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_NWT_VALIDATION_PROFILES_BY_CASE: dict[str, str] = {
    "boussinesq_fixed_head_piecewise_k_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    "boussinesq_uniform_recharge_piecewise_k_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    "dupuit_divide_river_1d": _NWT_VALIDATION_PROFILE_COMPLEX,
    "dupuit_fixed_head_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    "dupuit_uniform_recharge_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    "linearized_unconfined_drainage_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    "linearized_unconfined_boundary_piecewise_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
}


def _rmtree_onerror(func, path, exc_info) -> None:
    """Retry one failed ``rmtree`` step after clearing a read-only bit."""
    del exc_info
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree_with_retry(
    path: Path,
    *,
    retries: int = 5,
    base_delay_s: float = 0.2,
) -> None:
    """Remove one directory tree with retries for transient Windows locks."""
    if not path.exists():
        return

    last_error: PermissionError | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_rmtree_onerror)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            if attempt == retries - 1:
                raise
            time.sleep(base_delay_s * (attempt + 1))

    if last_error is not None:
        raise last_error


def remove_file_with_retry(
    path: Path,
    *,
    retries: int = 5,
    base_delay_s: float = 0.2,
) -> None:
    """Remove one file with retries for transient Windows locks/read-only bits."""
    if not path.exists():
        return

    last_error: PermissionError | None = None
    for attempt in range(retries):
        try:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            if attempt == retries - 1:
                raise
            time.sleep(base_delay_s * (attempt + 1))

    if last_error is not None:
        raise last_error


@dataclass(frozen=True, slots=True)
class ValidationRunResult:
    """Resolved workspace paths for one completed validation run."""

    case_dir: Path
    out_path: Path
    model_ws: Path
    postprocess_dir: Path
    particles_dir: Path
    run_returncode: int = 0
    run_stdout: str = ""
    run_stderr: str = ""


def _short_validation_name(value: str | Path, *, max_length: int = 28) -> str:
    """Return a deterministic filesystem-friendly validation folder name."""
    text = str(value).strip()
    if len(text) <= max_length:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    keep = max_length - len(digest) - 1
    return f"{text[:keep]}_{digest}"


def resolve_validation_results_dir(*, test_file: str | Path, run_name: str) -> Path:
    """Create one deterministic output directory for a validation run."""
    base_out_path = os.environ.get("HYDROMODPY_OUT_PATH")
    if base_out_path:
        results_root = Path(base_out_path).expanduser().resolve() / "validation"
    else:
        results_root = Path(tempfile.gettempdir()) / "hydromodpy_validation_outputs"

    test_stem = _short_validation_name(Path(test_file).resolve().stem)
    safe_run_name = _short_validation_name(run_name)
    out_dir = results_root / test_stem / safe_run_name
    if out_dir.exists():
        remove_tree_with_retry(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def resolve_model_workspace(
    out_path: Path,
    *,
    watershed_name: str | None = None,
    results_folder_name: str = "results_simulations",
    model_name: str | None = None,
    model_name_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """Resolve generated workspace folders for one completed launcher run."""
    if watershed_name is None:
        watershed_dirs = sorted(p for p in out_path.iterdir() if p.is_dir())
        assert watershed_dirs, f"No watershed folder found in {out_path}"
        watershed_dir = watershed_dirs[0]
    else:
        watershed_dir = out_path / watershed_name
        assert watershed_dir.is_dir(), f"Watershed folder not found: {watershed_dir}"

    results_dir = watershed_dir / results_folder_name
    assert results_dir.is_dir(), f"Results folder not found: {results_dir}"

    if model_name is not None:
        model_ws = results_dir / model_name
        assert model_ws.is_dir(), f"Model folder not found: {model_ws}"
    else:
        model_dirs = sorted(
            p
            for p in results_dir.iterdir()
            if p.is_dir()
            and not p.name.startswith("_")
            and (model_name_prefix is None or p.name.startswith(model_name_prefix))
        )
        assert model_dirs, f"No model folder found in {results_dir}"
        model_ws = model_dirs[0]

    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return model_ws, postprocess_dir, particles_dir


def run_example_script(
    *,
    script_path: Path,
    out_path: Path,
    out_env_var: str,
    extra_env: dict | None = None,
    script_args: list[str] | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run one HydroModPy launcher script as a subprocess."""
    env = os.environ.copy()
    env[out_env_var] = str(out_path)
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    run_args = [] if script_args is None else list(script_args)
    if os.environ.get("HYDROMODPY_COVERAGE"):
        wrapper = Path(__file__).resolve().parent / "coverage_runner.py"
        command = [sys.executable, str(wrapper), str(script_path), *run_args]
    else:
        command = [sys.executable, str(script_path), *run_args]

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    return completed


def _format_subprocess_failure(
    *,
    script_path: Path,
    command: list[str],
    completed: subprocess.CompletedProcess[str],
    workspace_error: AssertionError | None = None,
) -> str:
    message = (
        f"{script_path.name} failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Return code: {completed.returncode}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )
    if workspace_error is not None:
        message += f"\nWorkspace resolution failed: {workspace_error}"
    return message


def _build_validation_launcher_config(
    *,
    case_dir: Path,
    config_path: Path,
) -> Path:
    """Materialize one temporary launcher config with validation-only overrides."""
    profile_block = _NWT_VALIDATION_PROFILES_BY_CASE.get(case_dir.name)
    if profile_block is None:
        return config_path

    config_text = config_path.read_text(encoding="utf-8")
    marker = "[modflownwt.sgrid.planar]"
    insert_at = config_text.find(marker)
    if insert_at < 0:
        return config_path

    tmp_name = f".__validation_runtime_{config_path.stem}_{os.getpid()}.toml"
    tmp_path = case_dir / tmp_name
    tmp_text = f"{config_text[:insert_at]}{profile_block}\n{config_text[insert_at:]}"
    tmp_path.write_text(tmp_text, encoding="utf-8", newline="\n")
    return tmp_path


def run_launcher_validation_case(
    *,
    case_dir: Path,
    test_file: str | Path,
    timeout: int = 1800,
) -> ValidationRunResult:
    """Run one launcher-based validation case and resolve its output workspace."""
    metadata = load_case_metadata(case_dir)
    launcher_name = str(metadata.get("launcher", "launcher_simulation"))
    config_file = str(metadata.get("config_file", "config_modflownwt.toml"))
    workspace_cfg = dict(metadata.get("workspace", {}))

    launcher_script = REPO_ROOT / "examples" / launcher_name / f"{launcher_name}.py"
    case_id = str(metadata.get("case_id", case_dir.name))
    out_path = resolve_validation_results_dir(test_file=test_file, run_name=case_id)

    config_path = case_dir / config_file
    run_config_path = _build_validation_launcher_config(case_dir=case_dir, config_path=config_path)
    run_args = [str(run_config_path)]
    extra_env = {
        "HYDROMODPY_NO_DISPLAY": "1",
        "HYDROMODPY_NO_SAVE": "1",
    }
    try:
        completed = run_example_script(
            script_path=launcher_script,
            out_path=out_path,
            out_env_var="HYDROMODPY_OUT_PATH",
            extra_env=extra_env,
            script_args=run_args,
            timeout=timeout,
        )
    finally:
        if run_config_path != config_path and run_config_path.exists():
            try:
                remove_file_with_retry(run_config_path)
            except PermissionError:
                pass

    try:
        model_ws, postprocess_dir, particles_dir = resolve_model_workspace(
            out_path,
            watershed_name=workspace_cfg.get("watershed_name"),
            results_folder_name=str(workspace_cfg.get("results_folder_name", "results_simulations")),
            model_name=workspace_cfg.get("model_name"),
        )
    except AssertionError as exc:
        if completed.returncode != 0:
            command = (
                [sys.executable, str(Path(__file__).resolve().parent / "coverage_runner.py"), str(launcher_script), *run_args]
                if os.environ.get("HYDROMODPY_COVERAGE")
                else [sys.executable, str(launcher_script), *run_args]
            )
            raise AssertionError(
                _format_subprocess_failure(
                    script_path=launcher_script,
                    command=command,
                    completed=completed,
                    workspace_error=exc,
                )
            ) from exc
        raise
    return ValidationRunResult(
        case_dir=case_dir,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
    )
