"""Render didactic stream/seepage method sketches as SVG assets."""

from __future__ import annotations

from html import escape
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "_static" / "concepts" / "streams_and_seepage"

W = 1280
H = 740


class Svg:
    """Small SVG writer for deterministic documentation diagrams."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def raw(self, value: str) -> None:
        self.parts.append(value)

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        klass: str = "",
        rx: float = 0,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
    ) -> None:
        self.raw(
            f"<rect{_attrs({'x': x, 'y': y, 'width': w, 'height': h, 'rx': rx, 'class': klass, 'fill': fill, 'stroke': stroke, 'stroke-width': width})}/>"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        klass: str = "",
        marker: bool | str = False,
        stroke: str | None = None,
        width: float | None = None,
        dash: str | None = None,
    ) -> None:
        self.raw(
            f"<line{_attrs({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'class': klass, 'marker-end': _marker(marker), 'stroke': stroke, 'stroke-width': width, 'stroke-dasharray': dash})}/>"
        )

    def path(
        self,
        d: str,
        *,
        klass: str = "",
        marker: bool | str = False,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
        dash: str | None = None,
    ) -> None:
        self.raw(
            f"<path{_attrs({'d': d, 'class': klass, 'marker-end': _marker(marker), 'fill': fill, 'stroke': stroke, 'stroke-width': width, 'stroke-dasharray': dash})}/>"
        )

    def polygon(self, points: list[tuple[float, float]], *, klass: str = "") -> None:
        pts = " ".join(f"{x:g},{y:g}" for x, y in points)
        self.raw(f'<polygon points="{pts}" class="{klass}"/>')

    def polyline(
        self,
        points: list[tuple[float, float]],
        *,
        klass: str = "",
        marker: bool | str = False,
        fill: str | None = None,
    ) -> None:
        pts = " ".join(f"{x:g},{y:g}" for x, y in points)
        self.raw(
            f"<polyline{_attrs({'points': pts, 'class': klass, 'marker-end': _marker(marker), 'fill': fill})}/>"
        )

    def circle(self, cx: float, cy: float, r: float, *, klass: str = "") -> None:
        self.raw(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" class="{klass}"/>')

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        klass: str = "",
        anchor: str | None = None,
    ) -> None:
        self.raw(
            f"<text{_attrs({'x': x, 'y': y, 'class': klass, 'text-anchor': anchor})}>{escape(value)}</text>"
        )

    def multiline(
        self,
        x: float,
        y: float,
        lines: list[str],
        *,
        klass: str = "",
        line_height: int = 24,
        anchor: str | None = None,
    ) -> None:
        attrs = _attrs({"x": x, "y": y, "class": klass, "text-anchor": anchor})
        body = []
        for i, line in enumerate(lines):
            dy = 0 if i == 0 else line_height
            body.append(f'<tspan x="{x:g}" dy="{dy:g}">{escape(line)}</tspan>')
        self.raw(f"<text{attrs}>{''.join(body)}</text>")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_string(), encoding="utf-8")

    def to_string(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}" height="{H}" role="img">\n'
            + _defs()
            + "\n".join(self.parts)
            + "\n</svg>\n"
        )


def _attrs(values: dict[str, object | None]) -> str:
    rendered = []
    for key, value in values.items():
        if value is None or value == "":
            continue
        rendered.append(f'{key}="{escape(str(value), quote=True)}"')
    return " " + " ".join(rendered) if rendered else ""


def _marker(value: bool | str) -> str | None:
    if value == "orange":
        return "url(#arrowOrange)"
    if value:
        return "url(#arrowBlue)"
    return None


def _defs() -> str:
    return dedent(
        """
        <defs>
          <marker id="arrowBlue" viewBox="0 0 10 10" refX="8.6" refY="5"
                  markerWidth="12" markerHeight="12" orient="auto-start-reverse"
                  markerUnits="userSpaceOnUse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#1f5d86"/>
          </marker>
          <marker id="arrowOrange" viewBox="0 0 10 10" refX="8.6" refY="5"
                  markerWidth="12" markerHeight="12" orient="auto-start-reverse"
                  markerUnits="userSpaceOnUse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#a16207"/>
          </marker>
          <filter id="shadow" x="-10%" y="-10%" width="130%" height="130%">
            <feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#0f172a" flood-opacity="0.12"/>
          </filter>
          <style>
            .bg { fill: #f8fafc; }
            .title { font: 700 32px Segoe UI, Arial, sans-serif; fill: #10253d; }
            .subtitle { font: 400 18px Segoe UI, Arial, sans-serif; fill: #52657a; }
            .card { fill: #ffffff; stroke: #cbd8e6; stroke-width: 1.5; filter: url(#shadow); }
            .card-title { font: 700 15px Segoe UI, Arial, sans-serif; fill: #10253d; letter-spacing: .4px; }
            .card-text { font: 400 16px Segoe UI, Arial, sans-serif; fill: #26384d; }
            .eq-card { fill: #10253d; stroke: #10253d; stroke-width: 1.5; filter: url(#shadow); }
            .eq-title { font: 700 15px Segoe UI, Arial, sans-serif; fill: #dbeafe; letter-spacing: .4px; }
            .eq-text { font: 600 19px Consolas, Menlo, monospace; fill: #ffffff; }
            .eq-note { font: 400 14px Segoe UI, Arial, sans-serif; fill: #bfdbfe; }
            .panel { fill: #ffffff; stroke: #d5e0eb; stroke-width: 1.4; }
            .soil { fill: #dec99c; }
            .base { fill: #bec8be; opacity: .82; }
            .ground { fill: none; stroke: #66583a; stroke-width: 5; stroke-linecap: round; stroke-linejoin: round; }
            .head { fill: none; stroke: #1d78b8; stroke-width: 5; stroke-linecap: round; stroke-linejoin: round; }
            .surface-support { fill: none; stroke: #0f766e; stroke-width: 6; stroke-linecap: round; stroke-linejoin: round; }
            .stage-line { fill: none; stroke: #1d78b8; stroke-width: 3; stroke-dasharray: 8 7; }
            .surface-marker { fill: #ffffff; stroke: #0f766e; stroke-width: 3; }
            .head-marker { fill: #ffffff; stroke: #1d78b8; stroke-width: 3; }
            .flow { fill: none; stroke: #1f5d86; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
            .thin-flow { fill: none; stroke: #1f5d86; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
            .orange-flow { fill: none; stroke: #a16207; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
            .muted { fill: none; stroke: #94a3b8; stroke-width: 2; }
            .compare { fill: none; stroke: #1d78b8; stroke-width: 2.5; stroke-dasharray: 5 6; }
            .dash { fill: none; stroke: #a16207; stroke-width: 3; stroke-dasharray: 9 8; }
            .label { font: 700 15px Segoe UI, Arial, sans-serif; fill: #10253d; }
            .small { font: 400 14px Segoe UI, Arial, sans-serif; fill: #334155; }
            .hint { font: 600 16px Segoe UI, Arial, sans-serif; fill: #10253d; }
            .tag { fill: #e0f2fe; stroke: #b9dcf2; stroke-width: 1.2; }
            .tag-orange { fill: #fff7ed; stroke: #fed7aa; stroke-width: 1.2; }
            .grid { stroke: #dbe5ef; stroke-width: 1.2; }
            .source { fill: #ffdc73; stroke: #a16207; stroke-width: 3; }
            .cell-on { fill: #ffdc73; stroke: #a16207; stroke-width: 2.5; }
            .cell-off { fill: #f1f5f9; stroke: #94a3b8; stroke-width: 2.2; }
            .mask-active { fill: none; stroke: #1f5d86; stroke-width: 8; stroke-linecap: round; }
            .mask-inactive { fill: none; stroke: #cbd5e1; stroke-width: 8; stroke-linecap: round; }
            .concept { fill: #e8f3fb; stroke: #c6def0; stroke-width: 1.3; }
            .concept-text { font: 700 17px Segoe UI, Arial, sans-serif; fill: #10253d; }
          </style>
        </defs>
        """
    )


def _header(svg: Svg, title: str, subtitle: str) -> None:
    svg.rect(0, 0, W, H, klass="bg")
    svg.text(48, 52, title, klass="title")
    svg.text(48, 84, subtitle, klass="subtitle")


def _card(svg: Svg, x: int, y: int, w: int, h: int, title: str, lines: list[str]) -> None:
    svg.rect(x, y, w, h, klass="card", rx=14)
    svg.text(x + 22, y + 34, title.upper(), klass="card-title")
    svg.multiline(x + 22, y + 70, lines, klass="card-text", line_height=25)


def _equation(svg: Svg, x: int, y: int, w: int, h: int, lines: list[str], note: str) -> None:
    svg.rect(x, y, w, h, klass="eq-card", rx=14)
    svg.text(x + 22, y + 34, "CONCEPTUAL LAW", klass="eq-title")
    svg.multiline(x + 22, y + 75, lines, klass="eq-text", line_height=30)
    svg.text(x + 22, y + h - 24, note, klass="eq-note")


def _concept(svg: Svg, text: str) -> None:
    svg.rect(48, 660, 1184, 48, klass="concept", rx=12)
    svg.text(74, 691, text, klass="concept-text")


def _section_label(svg: Svg, x: int, y: int, value: str) -> None:
    svg.rect(x, y - 23, 112, 31, klass="tag", rx=16)
    svg.text(x + 56, y - 2, value, klass="label", anchor="middle")


def _smooth_path(points: list[tuple[float, float]]) -> str:
    if len(points) < 2:
        raise ValueError("A smooth path needs at least two points.")

    d = [f"M {points[0][0]:g} {points[0][1]:g}"]
    for i, p1 in enumerate(points[:-1]):
        p0 = points[i - 1] if i > 0 else p1
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2

        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C {c1[0]:g} {c1[1]:g}, {c2[0]:g} {c2[1]:g}, {p2[0]:g} {p2[1]:g}")
    return " ".join(d)


def _scaled(
    points: list[tuple[float, float]], x: int, y: int, scale: float
) -> list[tuple[float, float]]:
    return [(x + px * scale, y + py * scale) for px, py in points]


def _top_cards(
    svg: Svg, input_lines: list[str], eq_lines: list[str], note: str, result_lines: list[str]
) -> None:
    _card(svg, 48, 118, 285, 158, "Input object", input_lines)
    svg.line(352, 197, 405, 197, klass="thin-flow", marker=True)
    _equation(svg, 426, 118, 365, 158, eq_lines, note)
    svg.line(812, 197, 865, 197, klass="thin-flow", marker=True)
    _card(svg, 886, 118, 346, 158, "Solver or diagnostic output", result_lines)


def _cross_section(svg: Svg, x: int, y: int, scale: float = 1.0, *, head: str = "default") -> None:
    ground = [
        (0, 110),
        (80, 122),
        (150, 145),
        (215, 196),
        (265, 226),
        (345, 240),
        (430, 205),
        (515, 165),
        (620, 142),
    ]
    head_profiles = {
        "default": [
            (35, 154),
            (120, 169),
            (210, 202),
            (300, 228),
            (392, 237),
            (500, 229),
            (598, 222),
        ],
        "seepage": [
            (35, 158),
            (120, 177),
            (205, 214),
            (285, 229),
            (350, 219),
            (415, 199),
            (480, 176),
            (598, 188),
        ],
    }
    head_points = head_profiles[head]

    ground_points = _scaled(ground, x, y, scale)
    head_points = _scaled(head_points, x, y, scale)
    bottom_left = (x, y + 370 * scale)
    bottom_right = (x + 620 * scale, y + 370 * scale)

    soil_path = f"{_smooth_path(ground_points)} L {bottom_right[0]:g} {bottom_right[1]:g} L {bottom_left[0]:g} {bottom_left[1]:g} Z"
    svg.path(soil_path, klass="soil")
    bx, by = x, y + 300 * scale
    svg.rect(bx, by, 620 * scale, 70 * scale, klass="base")
    svg.path(_smooth_path(ground_points), klass="ground")
    svg.path(_smooth_path(head_points), klass="head")
    svg.text(x + 20 * scale, y + 95 * scale, "surface z_s(x)", klass="small")
    svg.text(x + 96 * scale, y + 188 * scale, "water-table head h(x)", klass="small")


def render_stream_stage_boundary() -> None:
    svg = Svg()
    _header(
        svg,
        "Stream line support: head-controlled exchange",
        "The river is a surface line, not a water body with thickness in this sketch.",
    )
    _top_cards(
        svg,
        ["surface line S_stream", "head/stage H_stream", "conductance C_stream"],
        ["q_stream = C_stream", "           * (H_stream - h)"],
        "Sign shown positive toward the aquifer.",
        ["computed q_stream", "gain or loss allowed", "budget term, not runoff input"],
    )

    _section_label(svg, 82, 310, "support")
    _section_label(svg, 520, 310, "equation")
    _section_label(svg, 1022, 310, "result")
    _cross_section(svg, 295, 305, 1.0)

    svg.path(
        _smooth_path([(535, 530), (590, 538), (640, 545), (705, 518), (765, 486)]),
        klass="surface-support",
    )
    svg.circle(610, 540, 8, klass="surface-marker")
    svg.circle(692, 522, 8, klass="surface-marker")
    svg.line(540, 472, 750, 472, klass="stage-line")
    svg.line(705, 472, 705, 516, klass="muted")
    svg.rect(758, 444, 134, 54, klass="tag", rx=10)
    svg.text(778, 467, "H_stream", klass="label")
    svg.text(778, 487, "prescribed head", klass="small")

    svg.path("M 435 500 C 500 514, 555 532, 610 540", klass="flow", marker=True)
    svg.path("M 860 408 C 820 454, 768 506, 692 522", klass="flow", marker=True)
    svg.rect(895, 384, 132, 54, klass="tag", rx=10)
    svg.text(913, 407, "q_stream", klass="label")
    svg.text(913, 427, "computed flux", klass="small")

    svg.text(548, 576, "zero-thickness support on the surface", klass="label")
    _concept(
        svg,
        "Read this as line exchange at the surface: prescribe H_stream on a support, solve h, compute q_stream.",
    )
    _write("method_stream_stage_boundary.svg", svg)


def render_seepage_drainage_operator() -> None:
    svg = Svg()
    _header(
        svg,
        "Seepage: surface-controlled emergence",
        "Water emerges where groundwater head reaches the local ground or channel surface.",
    )
    _top_cards(
        svg,
        ["surface support S_seep", "local surface z_s,i", "conductance C_seep"],
        ["q_seep,i = C_i", "       * max(h_i - z_s,i, 0)"],
        "Positive q_seep is groundwater outflow.",
        ["zero where h_i <= z_s,i", "positive where h_i > z_s,i", "local outflow_drain field"],
    )

    _section_label(svg, 82, 310, "support")
    _section_label(svg, 520, 310, "switch")
    _section_label(svg, 1022, 310, "outflow")
    _cross_section(svg, 295, 305, 1.0, head="seepage")

    svg.path(
        _smooth_path([(535, 530), (590, 538), (640, 545), (705, 518), (765, 486), (825, 470)]),
        klass="surface-support",
    )
    svg.rect(830, 558, 218, 36, klass="tag-orange", rx=10)
    svg.text(846, 582, "local surface z_s,i", klass="label")

    cells = [(525, 520, False), (605, 525, True), (685, 506, True), (765, 485, False)]
    for x, y, active in cells:
        surface_y = y + 20
        svg.circle(x + 24, surface_y, 8, klass="surface-marker")
        svg.rect(x, y, 48, 40, klass="cell-on" if active else "cell-off", rx=4)
        if active:
            svg.path(
                f"M {x + 24} {surface_y} C {x + 24} {surface_y - 30}, {x + 10} {surface_y - 54}, {x + 24} {surface_y - 82}",
                klass="orange-flow",
                marker="orange",
            )
    svg.line(650, 524, 650, 545, klass="compare")
    svg.circle(650, 524, 7, klass="head-marker")
    svg.circle(650, 545, 7, klass="surface-marker")
    svg.text(662, 526, "h_i", klass="small")
    svg.text(662, 551, "z_s,i", klass="small")
    svg.text(584, 432, "h_i > z_s,i", klass="label")
    svg.text(684, 432, "seepage", klass="label")
    svg.text(506, 585, "dry", klass="small")
    svg.text(768, 585, "dry", klass="small")
    svg.path("M 430 480 C 500 505, 560 525, 610 545", klass="flow", marker=True)
    svg.path("M 890 455 C 820 482, 755 505, 709 526", klass="flow", marker=True)

    _concept(
        svg,
        "Read this as seepage through a surface line: solve h, compare with z_s,i, release only where h_i exceeds the surface.",
    )
    _write("method_seepage_drainage_operator.svg", svg)


def render_simulated_active_postprocess() -> None:
    svg = Svg()
    _header(
        svg,
        "Simulated active seepage network: routed post-processing",
        "The active network is inferred from surface emergence points, not from a river volume.",
    )
    _top_cards(
        svg,
        ["surface emergence q_i", "q_i+ = max(q_i, 0)", "routing graph upstream(i)"],
        ["A_i = q_i+ + sum(A_j)", "m_i = 1[A_i >= Q_thr]"],
        "j runs over upstream cells or faces.",
        ["accumulation_flux A_i", "thresholded mask m_i", "comparison to reference lines"],
    )

    svg.rect(58, 315, 495, 285, klass="panel", rx=14)
    svg.text(86, 350, "surface seepage outflow", klass="label")
    left, top, width, height = 92, 378, 410, 160
    for i in range(10):
        x = left + width * i / 9
        svg.line(x, top, x, top + height, klass="grid")
    for j in range(5):
        y = top + height * j / 4
        svg.line(left, y, left + width, y, klass="grid")
    route = [(150, 412), (222, 455), (300, 485), (383, 518), (462, 530)]
    for x, y in route:
        svg.circle(x, y, 16, klass="source")
    for (x1, y1), (x2, y2) in zip(route, route[1:]):
        svg.line(x1, y1, x2, y2, klass="flow", marker=True)
    svg.text(100, 572, "q_i+ emergence sources on surface cells or faces", klass="small")

    svg.line(575, 458, 662, 458, klass="thin-flow", marker=True)
    svg.rect(690, 330, 220, 244, klass="panel", rx=14)
    svg.text(718, 365, "route downstream", klass="label")
    svg.multiline(
        718,
        407,
        ["1. keep positive flux", "2. accumulate on graph", "3. apply threshold"],
        klass="card-text",
        line_height=32,
    )
    svg.rect(720, 505, 160, 45, klass="tag", rx=10)
    svg.text(747, 534, "A_i -> m_i", klass="label")

    svg.line(934, 458, 992, 458, klass="thin-flow", marker=True)
    svg.rect(1010, 335, 185, 220, klass="panel", rx=14)
    svg.text(1043, 370, "active mask", klass="label")
    svg.line(1048, 438, 1085, 466, klass="mask-inactive")
    svg.line(1085, 466, 1132, 495, klass="mask-active")
    svg.line(1132, 495, 1160, 523, klass="mask-active")
    svg.circle(1085, 466, 8, klass="source")
    svg.circle(1132, 495, 8, klass="source")
    svg.text(1040, 535, "diagnostic view", klass="small")

    _concept(
        svg,
        "Read this as a view layer: water-budget fields stay raw; active linework is a thresholded diagnostic.",
    )
    _write("method_simulated_active_postprocess.svg", svg)


def _write(name: str, svg: Svg) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    svg.save(OUT / name)


def main() -> None:
    render_stream_stage_boundary()
    render_seepage_drainage_operator()
    render_simulated_active_postprocess()


if __name__ == "__main__":
    main()
