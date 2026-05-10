"""Root-level calibration adapters that depend on the public Project facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class ProjectTrialPromotionProvider:
    """Promote calibration trials through the public ``Project`` facade."""

    def promote_trial(
        self,
        cfg_path: Path | str,
        values: Mapping[str, float],
        *,
        paths: Mapping[str, str] | None = None,
        name: str | None = None,
        tags: Sequence[str] = (),
        session_id: str | None = None,
    ) -> str:
        """Run the full simulation pipeline with calibration values baked in."""
        from hydromodpy.calibration.runners.trial import _set_by_path
        from hydromodpy.project import Project

        resolved_cfg_path = Path(cfg_path).expanduser().resolve()
        project = Project(resolved_cfg_path)
        try:
            if paths:
                for pname, pvalue in values.items():
                    dotted = paths.get(pname)
                    if dotted:
                        _set_by_path(project.cfg, dotted, pvalue)
                run = project.run(name=name or "promoted")
            else:
                run = project.run(name=name or "promoted", **dict(values))
            sim_id = run.sim_id

            tag_list: list[str] = list(tags)
            if session_id:
                tag_list.append(f"calibration:{session_id}")
            if tag_list:
                store = getattr(project, "store", None) or getattr(project, "_store", None)
                writer = getattr(store, "write_tags", None)
                if callable(writer):
                    try:
                        writer(sim_id, tag_list)
                    except Exception:
                        logger.exception(
                            "Failed to attach tags %s to sim %s",
                            tag_list,
                            sim_id,
                        )
        finally:
            project.close()

        return sim_id


__all__ = ["ProjectTrialPromotionProvider"]
