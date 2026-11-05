"""The window of steps a run executes: from_step, until_step and the model phase."""

from __future__ import annotations

from hydromodpy.core.exceptions import ConfigError


def resolve_step_index(step: str, steps: tuple) -> int:
    """Return the position of the step named *step* in *steps*.

    A step is named by its ``name``, one of
    :data:`~hydromodpy.core.pipeline_steps.STEP_NAMES`. An index would move when a
    version inserts a step, so it is refused, and a class name is no contract.
    """
    if not isinstance(step, str):
        known = ", ".join(getattr(obj, "name", type(obj).__name__) for obj in steps)
        raise ConfigError(
            f"A pipeline step is named, not numbered: got {step!r}. Known steps: {known}."
        )
    for index, obj in enumerate(steps):
        if getattr(obj, "name", None) == step:
            return index
    known = ", ".join(getattr(obj, "name", type(obj).__name__) for obj in steps)
    raise ConfigError(f"Unknown pipeline step: {step!r}. Known steps: {known}.")


def bounded_step_index(step: str | None, steps: tuple) -> int | None:
    """Resolve a step bound, ``None`` when there is none."""
    return None if step is None else resolve_step_index(step, steps)


def refuse_an_empty_window(
    from_step: str | None, from_idx: int | None, until_step: str | None, until_idx: int | None
) -> None:
    """Refuse a step window whose start comes after its end."""
    if from_idx is not None and until_idx is not None and from_idx > until_idx:
        raise ConfigError(f"from_step {from_step!r} is past until_step {until_step!r}.")


def window_stops_before_the_model(
    until_step: str | None, until_idx: int | None, first_model_step: int, resume: str | None
) -> bool:
    """Say whether a window ends before ``setup_process``.

    Such a window reaches no step able to open a run, so it is not a run and claims no
    directory, and it keeps no journal to resume from.
    """
    head_only = until_idx is not None and until_idx < first_model_step
    if head_only and resume is not None:
        raise ConfigError(
            f"until_step {until_step!r} stops before 'setup_process', so the run keeps no "
            f"journal to resume from. Drop --resume, or widen the window."
        )
    return head_only


def model_phase_index(steps: tuple) -> int:
    """Return the index of the first step that consumes the shared model phase.

    ``0`` when the pipeline declares no ``setup_process``: an ad-hoc step list
    makes no claim about a model phase, so every window is treated as needing
    one, which is what the canonical pipeline did before the bound existed.
    """
    for index, step in enumerate(steps):
        if getattr(step, "name", None) == "setup_process":
            return index
    return 0


def step_window(
    steps: tuple, from_step: str | None, until_step: str | None, resume: str | None
) -> tuple[int | None, int | None, bool]:
    """Return ``(from_idx, until_idx, head_only)`` of the window a run asks for.

    Refuses an unknown step, a window whose start is past its end, and a head-only
    window that resumes.
    """
    until_idx = bounded_step_index(until_step, steps)
    from_idx = bounded_step_index(from_step, steps)
    refuse_an_empty_window(from_step, from_idx, until_step, until_idx)
    head_only = window_stops_before_the_model(
        until_step, until_idx, model_phase_index(steps), resume
    )
    return from_idx, until_idx, head_only
