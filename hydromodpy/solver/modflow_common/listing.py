"""Reading the MODFLOW listing file: budget discrepancies, failure lines and the XT3D hint."""

from __future__ import annotations

import re
from pathlib import Path

_PERCENT_DISCREPANCY_RE = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([-+0-9.Ee]+)")


def percent_discrepancies(listing_dir: Path) -> list[float]:
    """Return every water-budget PERCENT DISCREPANCY a per-model listing prints.

    Best-effort and never raises: scans every ``*.lst`` except the simulation
    listing, and every ``*.list``, the extension FloPy gives the MODFLOW-NWT
    listing, in name order, and returns the values in the order they appear.

    A MODFLOW budget block prints two of them on one line, the cumulative
    volumes since the start of the simulation and the rates for the time step
    just solved. Both are kept: neither is more the budget than the other.
    """
    values: list[float] = []
    try:
        listings = sorted([*listing_dir.glob("*.lst"), *listing_dir.glob("*.list")])
    except OSError:
        return values
    for listing in listings:
        if listing.name == "mfsim.lst":
            continue
        try:
            text = listing.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _PERCENT_DISCREPANCY_RE.finditer(text):
            try:
                values.append(float(match.group(1)))
            except ValueError:
                continue
    return values


_MODEL_BUDGET_HEADER_RE = re.compile(r"^\s*VOLUM\w*\s+BUDGET\s+FOR\s+ENTIRE\s+MODEL", re.IGNORECASE)
_ANY_BUDGET_HEADER_RE = re.compile(r"^\s*[\w ]*BUDGET\s+FOR\s+ENTIRE\s+MODEL", re.IGNORECASE)


def model_percent_discrepancies(listing_dir: Path) -> list[float]:
    """Return the PERCENT DISCREPANCY of the model volume budget only.

    A MODFLOW 6 listing prints one budget block per package family (SFR, LAK,
    water mover) before the ``VOLUME BUDGET FOR ENTIRE MODEL`` block. A package
    block divides by its own small flows, so a lake package at 2 per cent sat
    beside a model at 0.02 per cent. This keeps the model block alone. A listing
    with no recognisable block header falls back to every value, so a backend
    that prints a bare figure still reports it.
    """
    try:
        listings = sorted([*listing_dir.glob("*.lst"), *listing_dir.glob("*.list")])
    except OSError:
        return []
    values: list[float] = []
    for listing in listings:
        if listing.name == "mfsim.lst":
            continue
        try:
            text = listing.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        in_model_block = None  # None: no header seen yet
        for line in text.splitlines():
            if _MODEL_BUDGET_HEADER_RE.match(line):
                in_model_block = True
                continue
            if _ANY_BUDGET_HEADER_RE.match(line):
                in_model_block = False
                continue
            if in_model_block is False:
                continue
            for match in _PERCENT_DISCREPANCY_RE.finditer(line):
                try:
                    values.append(float(match.group(1)))
                except ValueError:
                    continue
    return values


def last_percent_discrepancy(listing_dir: Path) -> float | None:
    """Return the final water-budget PERCENT DISCREPANCY from a per-model listing.

    Best-effort and never raises: returns the last parsed value, or None when
    none is found.
    """
    values = percent_discrepancies(listing_dir)
    return values[-1] if values else None


def worst_percent_discrepancy(listing_dir: Path) -> float | None:
    """Return the signed PERCENT DISCREPANCY of largest magnitude, or None.

    The last block is not the worst one. A transient run that loses its budget
    in the middle and recovers by the final time step reports a clean final
    number, and :func:`last_percent_discrepancy` reads exactly that number. A
    deep-aquifer recession measured here closed the simulation at -190 % after
    touching -200 %, so even a run that never recovers understates itself.

    Recorded and not acted upon. A percent discrepancy divides by the mean of
    the inflow and the outflow, so the instant a transient model routes almost
    no water -- an intermittent reach going dry, a lake stage crossing its sill,
    the tail of any recession -- the quotient is large while the imbalance it
    describes is negligible. Rejecting on this number would refuse sound runs
    for arithmetic reasons. What a guard needs is the absolute imbalance against
    the scale of the run, which the listing also prints and nothing parses yet.

    Ties keep the first reading of that magnitude, so two opposite signs of
    equal size report the earlier one.
    """
    values = percent_discrepancies(listing_dir)
    if not values:
        return None
    return max(values, key=abs)


_SIMULATION_FAILURE_RE = re.compile(
    r"did not converge|convergence failure|premature termination", re.IGNORECASE
)


def simulation_listing_failure_lines(model_dir: Path, *, max_lines: int = 10) -> list[str]:
    """Return the lines of ``mfsim.lst`` that say why MODFLOW 6 stopped.

    Best-effort and never raises. Keeps the convergence-failure lines and the
    whole ``ERROR REPORT`` block MF6 prints at the end, without duplicates and
    with runs of spaces collapsed, and returns the last ``max_lines`` of them.
    A missing listing means mf6 never started or could not create it.
    """
    listing = model_dir / "mfsim.lst"
    try:
        text = listing.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ["mfsim.lst was not written: mf6 did not start or could not create it"]
    picked: list[str] = []
    in_report = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if line.endswith("ERROR REPORT:"):
            in_report = True
        if (in_report or _SIMULATION_FAILURE_RE.search(line)) and line not in picked:
            picked.append(line)
    return picked[-max_lines:]


def xt3d_failure_hint(model_dir: Path) -> str:
    """Return a hint naming the XT3D switch when the written NPF uses XT3D.

    XT3D can keep the Newton outer loop cycling on some triangle meshes.
    The user needs the config key that turns it off.
    """
    for npf in sorted(Path(model_dir).glob("*.npf")):
        try:
            text = npf.read_text(errors="replace")
        except OSError:
            continue
        in_options = False
        for raw in text.splitlines():
            line = raw.strip().upper()
            if line.startswith("BEGIN OPTIONS"):
                in_options = True
            elif line.startswith("END OPTIONS"):
                break
            elif in_options and line.split()[:1] == ["XT3D"]:
                return (
                    " The NPF package uses XT3D. If the outer iterations cycle,"
                    " set mf6_enable_xt3d = false under [solver.modflow6.runtime]"
                    " and run again."
                )
    return ""
