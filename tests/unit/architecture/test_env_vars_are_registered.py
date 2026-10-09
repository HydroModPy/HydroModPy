"""Every ``HMP_*`` environment variable the code names has a row in ``hydromodpy.core.env``.

The variables are read where they are needed, in many files, and the pages
listed them by hand, each page a different subset. The registry is the one
list, and the contributor page renders it. This gate keeps the two directions honest: a name
the code writes without a row fails here, and so does a row whose variable
nothing reads any more.

The scan is ``tools.docs.contribute_data.env_var_references``: a whole string
literal in a Python file, outside ``__all__``, and any occurrence in the CI
workflows, ``docs/Makefile`` and the ``Dockerfile``. A literal that looks like
a variable and is something else goes in :data:`NOT_ENVIRONMENT`, with why.
"""

from __future__ import annotations

from hydromodpy.core.env import ENV_SCOPES, ENV_VARS, env_var
from tools.docs.contribute_data import env_var_references

NOT_ENVIRONMENT: dict[str, str] = {
    "HMP_PERIOD": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_SIM_ID": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_TIMESTAMP": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_UNITS": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_VARIABLE": "GeoTIFF tag written by results/exporters/geotiff.py",
}


def _registered(name: str) -> bool:
    try:
        env_var(name)
    except KeyError:
        return False
    return True


def test_every_variable_the_code_names_has_a_row() -> None:
    names = set(env_var_references()) - set(NOT_ENVIRONMENT)
    missing = sorted(name for name in names if not _registered(name))
    assert missing == [], (
        "These HMP_* names appear in the code without a row in hydromodpy/core/env.py. "
        "Add a row (name, default, scope, description), or add the name to NOT_ENVIRONMENT "
        f"in this file when it is not an environment variable: {missing}"
    )


def test_every_row_names_a_variable_the_code_reads() -> None:
    names = set(env_var_references())
    stale = sorted(
        var.name
        for var in ENV_VARS
        if not any(n == var.name or (var.prefix and n.startswith(var.name)) for n in names)
    )
    assert stale == [], f"hydromodpy/core/env.py lists variables nothing reads: {stale}"


def test_every_exclusion_is_still_written_somewhere() -> None:
    names = set(env_var_references())
    stale = sorted(set(NOT_ENVIRONMENT) - names)
    assert stale == [], f"NOT_ENVIRONMENT lists names the code no longer writes: {stale}"


def test_a_row_is_complete_and_unique() -> None:
    seen: set[str] = set()
    for var in ENV_VARS:
        assert var.name.startswith("HMP_"), var.name
        assert var.name not in seen, f"{var.name} has two rows"
        seen.add(var.name)
        assert var.scope in ENV_SCOPES, f"{var.name}: unknown scope {var.scope!r}"
        assert var.default.strip(), f"{var.name}: say what happens when it is unset"
        assert len(var.description.split()) >= 6, f"{var.name}: the description is too short"
