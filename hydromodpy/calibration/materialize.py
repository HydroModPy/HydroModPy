"""Materialise a self-contained TOML overlay for one calibration candidate.

The overlay inherits the target simulation config via ``base_config`` and
rewrites each configured parameter at its target dotted path (honouring
``mode="replace"`` or ``"scale"``). The resulting file can be loaded by
:class:`hydromodpy.Project` and re-run independently of the calibration
session, which makes it the natural hand-off for sharing the best
candidate of a session or replaying a single trial.

The overlay is rendered through :mod:`hydromodpy.core.toml_io.writer`
so the output remains valid TOML and round-trips through :mod:`tomllib`
even in lightweight environments where external TOML writer packages are
not installed. The ``base_config`` argument accepts either a path to a
TOML file on disk or an in-memory
:class:`~hydromodpy.config.HydroModPyConfig` instance; the latter is
useful when the calibration loop is driven from Python code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.calibration.parameters import ParameterSpace
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.toml_io.writer import dump as dump_toml


def _sanitize_label(label: str) -> str:
    """Return one filesystem-safe candidate label."""
    text = str(label).strip().lower()
    if not text:
        raise ValueError("candidate_label cannot be empty")
    return re.sub(r"[^a-z0-9_.-]+", "_", text)


def _split_target_path(target: str) -> tuple[str, ...]:
    return tuple(part for part in str(target).strip().split(".") if part)


def _lookup_nested(payload: Mapping[str, Any], dotted: Sequence[str]) -> Any:
    cursor: Any = payload
    for part in dotted:
        if isinstance(cursor, Mapping) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


def _assign_nested(payload: dict[str, Any], dotted: Sequence[str], value: Any) -> None:
    cursor = payload
    for part in dotted[:-1]:
        sub = cursor.get(part)
        if not isinstance(sub, dict):
            sub = {}
            cursor[part] = sub
        cursor = sub
    cursor[dotted[-1]] = value


def _resolve_overlay_target_path(
    base_payload: Mapping[str, Any],
    dotted: Sequence[str],
) -> tuple[str, ...]:
    """Map canonical parameter paths onto the source TOML grammar."""
    if len(dotted) < 4 or tuple(dotted[:2]) != ("flow", "param"):
        return tuple(dotted)
    param_payload = _lookup_nested(base_payload, dotted[:3])
    if not isinstance(param_payload, Mapping):
        return tuple(dotted)

    field_name = dotted[3]
    tail = tuple(dotted[4:])
    if field_name in {"value", "values"} and isinstance(param_payload.get("field"), Mapping):
        return tuple(dotted[:3]) + ("field", field_name) + tail
    return tuple(dotted)


def _coerce_for_toml(value: Any) -> Any:
    """Recursively map a Python value into TOML-writer-friendly values.

    - :class:`pathlib.Path` becomes its string form.
    - :class:`pint.Quantity`-like objects become ``"<magnitude> <units>"``.
    - Tuples become lists.
    - ``None`` is dropped by callers.
    """
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        return f"{value.magnitude} {value.units:~}"
    if isinstance(value, (list, tuple)):
        return [_coerce_for_toml(v) for v in value if v is not None]
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, sub in value.items():
            if sub is None:
                continue
            out[str(key)] = _coerce_for_toml(sub)
        return out
    return value


def write_overlay_toml(path: Path, payload: Mapping[str, Any]) -> None:
    """Render *payload* to TOML at *path*.

    Public helper kept so callers that need to drop a calibration overlay
    next to a TOML file (for example the Python-mode of
    :meth:`Project.calibrate`) can rely on a stable serialisation entry
    point rather than reaching into a private symbol.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    coerced = _coerce_for_toml(payload)
    if not isinstance(coerced, dict):
        raise TypeError("write_overlay_toml expects a mapping payload")
    with open(path, "wb") as fh:
        dump_toml(coerced, fh)


def _load_base_payload(
    base_config: Path | str | BaseModel,
) -> tuple[dict[str, Any], Path | None]:
    """Resolve ``base_config`` into a dict payload and an optional source path.

    A ``HydroModPyConfig`` instance (or any Pydantic ``BaseModel``) is
    dumped through ``model_dump`` (alias aware) so the rendered overlay
    matches the TOML schema. A path is parsed via :mod:`tomllib`.
    ``base_path`` is ``None`` when the caller passed an in-memory config
    without a backing file.
    """

    if isinstance(base_config, BaseModel):
        payload = base_config.model_dump(mode="json", exclude_none=True)
        return payload, None
    base_path = Path(base_config).expanduser().resolve()
    if not base_path.is_file():
        raise FileNotFoundError(f"base_config not found: {base_path}")
    return load_toml_with_base_config(base_path), base_path


def _apply_parameter_mode(
    *, base_value: Any, candidate_value: float, mode: str, param_name: str
) -> float:
    mode_key = str(mode).strip().lower()
    if mode_key == "scale":
        if base_value is None:
            raise ValueError(
                f"Parameter {param_name!r}: scale mode requires a numeric base "
                f"value at the target path in the simulation TOML."
            )
        try:
            base = float(base_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Parameter {param_name!r}: scale mode requires a numeric base "
                f"value; got {base_value!r}."
            ) from exc
        return float(base * float(candidate_value))
    if mode_key == "replace":
        return float(candidate_value)
    raise ValueError(
        f"Parameter {param_name!r}: unsupported mode {mode!r} (expected 'replace' or 'scale')."
    )


def _format_path_for_overlay(path: Path, base_dir: Path | None) -> str:
    if base_dir is None:
        return str(path)
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def materialize_candidate(
    base_config: Path | str | BaseModel,
    params: Mapping[str, float],
    space: ParameterSpace,
    out_dir: Path | str,
    *,
    candidate_label: str | None = None,
    iteration_index: int | None = None,
    run_id: str | None = None,
    workspace_root: Path | str | None = None,
    extra_sections: Mapping[str, Mapping[str, Any]] | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Write a standalone override TOML for one calibration candidate.

    Parameters
    ----------
    base_config
        Path to the target simulation TOML or an in-memory
        :class:`~hydromodpy.config.HydroModPyConfig` instance. When a
        config object is passed, the overlay is built from
        ``model_dump`` and ``base_config`` in the overlay falls back to
        ``base_dir`` (when supplied) so the file remains rechargeable.
    params
        Candidate values keyed by parameter name (must cover every
        parameter in ``space`` that has a ``target`` or ``path``).
    space
        Calibration parameter space declaring dotted target paths and
        per-parameter ``mode`` (``"replace"`` / ``"scale"``).
    out_dir
        Directory under which the overlay is written. A ``candidate_label``
        or ``iteration_index`` argument picks the subfolder name.
    candidate_label
        Filesystem-safe label (e.g. ``"truth"``). Either ``candidate_label``
        or ``iteration_index`` must be supplied.
    iteration_index
        Iteration number when no explicit label is given. Produces a
        folder like ``iter_0042``.
    run_id
        Value to write at ``simulation.run_id`` in the overlay.
    workspace_root
        Value to write at ``workspace.root``. Required when the parent
        simulation TOML does not already declare a workspace root.
    extra_sections
        Optional mapping of additional TOML sections (e.g.
        ``{"display": {"enabled": False}}``) applied on top of the overlay.
    base_dir
        Reference directory for relative path rewriting. When supplied,
        ``base_config`` and ``workspace.root`` paths inside the overlay
        are emitted relative to this directory; otherwise absolute paths
        are written (the historical behaviour).

    Returns
    -------
    Path
        Absolute path to the written overlay TOML.
    """
    base_raw, base_path = _load_base_payload(base_config)

    out_dir_path = Path(out_dir).expanduser().resolve()
    if candidate_label is not None:
        iter_id = _sanitize_label(candidate_label)
    elif iteration_index is not None:
        iter_id = f"iter_{int(iteration_index):04d}"
    else:
        raise ValueError("materialize_candidate requires candidate_label or iteration_index")
    candidate_dir = out_dir_path / iter_id
    overlay_path = candidate_dir / "candidate_override.toml"

    base_dir_resolved = Path(base_dir).expanduser().resolve() if base_dir is not None else None
    if base_path is None and base_dir_resolved is None:
        raise ValueError(
            "materialize_candidate requires base_dir when base_config is an in-memory config"
        )

    overlay: dict[str, Any] = deepcopy(base_raw) if base_path is None else {}
    if base_path is not None:
        overlay["base_config"] = _format_path_for_overlay(base_path, base_dir_resolved)

    if run_id is not None:
        simulation_section = dict(overlay.get("simulation", {}))
        simulation_section["run_id"] = str(run_id)
        overlay["simulation"] = simulation_section

    workspace_section: dict[str, Any] = dict(base_raw.get("workspace", {}))
    if workspace_root is not None:
        ws_path = Path(workspace_root).expanduser().resolve()
        workspace_section["root"] = _format_path_for_overlay(ws_path, base_dir_resolved)
    elif not workspace_section.get("root"):
        if base_path is not None:
            workspace_section["root"] = _format_path_for_overlay(
                base_path.parent, base_dir_resolved
            )
        elif base_dir_resolved is not None:
            workspace_section["root"] = str(base_dir_resolved)
    if workspace_section:
        overlay["workspace"] = workspace_section

    for param in space:
        target = param.target if param.target is not None else param.path
        if target is None:
            continue
        if param.name not in params:
            raise ValueError(f"Parameter {param.name!r} missing from candidate params mapping")
        dotted = _split_target_path(target)
        overlay_dotted = _resolve_overlay_target_path(base_raw, dotted)
        base_value = _lookup_nested(base_raw, overlay_dotted)
        resolved = _apply_parameter_mode(
            base_value=base_value,
            candidate_value=float(params[param.name]),
            mode=str(param.mode),
            param_name=param.name,
        )
        _assign_nested(overlay, overlay_dotted, resolved)

    if extra_sections:
        for section_name, section_payload in extra_sections.items():
            overlay[str(section_name)] = dict(section_payload)

    write_overlay_toml(overlay_path, overlay)
    return overlay_path


__all__ = ["materialize_candidate", "write_overlay_toml"]
