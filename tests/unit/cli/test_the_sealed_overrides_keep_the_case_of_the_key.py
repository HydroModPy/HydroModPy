"""``lineage.overrides`` keeps the case of an ``HMP_SET_*`` key.

``HMP_SET_flow__param__K__field__value`` sets ``flow.param.K``: the override
applied to the document keeps the case. The trace sealed with the run wrote
``flow.param.k.field.value``, a key no document has.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.commands.run import _materialize_effective_toml


def test_the_trace_names_the_key_the_override_set(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "project.toml"
    config.write_text('[simulation]\nname = "case"\n', encoding="utf-8")
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-5")

    temp, raw, lineage = _materialize_effective_toml(
        config, args=argparse.Namespace(overlay=[], set_overrides=[])
    )
    if temp is not None:
        temp.unlink()

    assert raw["flow"]["param"]["K"]["field"]["value"] == 1e-5
    assert lineage == {"flow.param.K.field.value": 1e-5}
