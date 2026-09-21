"""A Methods paragraph the run writes about itself.

Borrowed from fMRIPrep, where it is the single highest-yield thing the project
does for reproducibility: the run emits the prose describing what it did, with
citations, and the author pastes it. Two properties make it worth more than a
hand-written paragraph. It cannot drift, because it is generated from the same
declarations the run executed. And it is conditioned on what actually ran, not on
what was planned, so a two-stage method whose second stage never finished says so
instead of describing a calibration that did not happen.

On a platform this stops being a convenience. Whoever reads a conductivity in a
note of synthesis is not whoever produced it, and this paragraph is the only
object by which they can know what it rests on without reading Python.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from hydromodpy.calibration.protocols.registry import get_protocol


def methods_paragraph(
    name: str,
    *,
    stages_that_ran: Sequence[str] = (),
    calibrated: Mapping[str, float] | None = None,
    chosen: Mapping[str, object] | None = None,
    options: Sequence[Mapping[str, object]] | None = None,
    backend: str | None = None,
    conditional_widths: Mapping[str, str] | None = None,
    absent_widths: Mapping[str, str] | None = None,
) -> str:
    """Return the Methods prose for one calibration that ran.

    ``stages_that_ran`` names the stages that completed, so the sentence
    describes the run rather than the plan. ``calibrated`` carries the values the
    search returned, ``chosen`` the settings this file set on keys the protocol
    departs from its publication on, ``options`` the protocol options it moved off
    the recipe, and ``backend`` the solver, whose support status is stated when it
    is not one this repository tests.

    ``conditional_widths`` names, per stage, a parameter uncertainty that WAS
    reported but is conditional rather than absolute -- typically frozen
    upstream values it does not carry. A conditional width read as an absolute
    one is a wrong number, not a missing detail, so it belongs in the paragraph
    a reader actually cites, not only in a log line.

    ``absent_widths`` names, per stage, why NO parameter uncertainty was built
    at all (a reused stage that was not resolved, or a stage with no residual
    vector to take a width from). This must stay a separate key from
    ``conditional_widths``: a stage with nothing to report is not the same
    claim as a stage reporting a number that comes with a caveat, and folding
    the two together reads as if every listed stage carried a width.
    """
    protocol = get_protocol(name)
    parts: list[str] = []

    citation = "; ".join(
        f"{reference.authors.split(',')[0].strip()} et al., {reference.year}"
        for reference in protocol.references[:1]
    )
    parts.append(
        f"Hydraulic properties were calibrated with the {protocol.title!r} protocol "
        f"({protocol.name} version {protocol.version}), after {citation}."
    )

    ran = [str(stage) for stage in stages_that_ran]
    if not ran:
        parts.append("No stage of the protocol completed, so no calibrated value is reported.")
        return " ".join(parts)

    described = [str(text).rstrip(".") for text in list(protocol.stages)[: len(ran)]]
    parts.append(
        f"{len(ran)} of the {len(protocol.stages)} stages completed: "
        + "; ".join(f"({index}) {text}" for index, text in enumerate(described, start=1))
        + "."
    )
    if len(ran) < len(protocol.stages):
        parts.append(
            "The remaining stage did not complete, so any parameter it would have "
            "calibrated keeps the value it entered the calibration with."
        )

    if calibrated:
        rendered = ", ".join(f"{key} = {value:.4g}" for key, value in sorted(calibrated.items()))
        parts.append(f"The calibration returned {rendered}.")

    departures = [
        deviation
        for deviation in protocol.deviations
        if chosen is not None and deviation.key in chosen
    ]
    if departures:
        listed = "; ".join(
            f"{deviation.key} was set to {chosen[deviation.key]!r} where the publication "
            f"uses {deviation.paper}"
            for deviation in departures
            if chosen is not None
        )
        parts.append(f"This run departs from the published method as follows: {listed}.")

    if options:
        listed = ", ".join(
            f"{item['key']} = {item['here']!r} instead of {item['recipe']!r}" for item in options
        )
        parts.append(f"Protocol options were moved off the recipe: {listed}.")

    if conditional_widths:
        listed = "; ".join(f"{stage}: {note}" for stage, note in sorted(conditional_widths.items()))
        parts.append(f"Reported parameter uncertainty is conditional on the following: {listed}.")

    if absent_widths:
        listed = "; ".join(f"{stage}: {note}" for stage, note in sorted(absent_widths.items()))
        parts.append(f"No parameter uncertainty was built for: {listed}.")

    if backend:
        verdict = protocol.support.get(str(backend))
        if verdict == "expected_untested":
            parts.append(
                f"The protocol was run on the {backend} backend, on which it is expected "
                "to work but is not covered by a test case."
            )
        elif verdict == "unsupported":
            parts.append(f"The protocol is not supported on the {backend} backend.")

    parts.append(
        "Full citations: " + " ".join(reference.cite() for reference in protocol.references)
    )
    return " ".join(parts)


__all__ = ["methods_paragraph"]
