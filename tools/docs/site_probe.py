"""Probe the built site in a browser: accessibility, overflow and header height.

Usage:
    python -m tools.docs.site_probe SITE [--axe PATH] [--chromium PATH]
                                         [--pages NAME ...] [--no-axe] [--json FILE]

SITE is the built HTML folder (``docs/build/html``). The probe serves it on a
local port and opens about 23 pages, one of each type: the home, a door index, a
generated reference page, a staircase step, a theory page with maths, the explorer,
the search page, a Contribute page. On each page it checks:

- axe-core finds no violation of WCAG 2.1 A and AA, in the light and the dark
  theme (a violation listed in ``site_probe_allow.toml`` is skipped, with its
  reason);
- at 390 px the page does not scroll sideways;
- the header is one row at 390 to 1440 px: no taller than ``HEADER_MAX``.

It needs playwright (``pip install playwright``), a Chromium (``playwright
install chromium``, or ``--chromium /usr/bin/chromium``) and axe-core
(``npm install axe-core``; ``--axe`` gives the path of ``axe.min.js``). Exit
code 1 when a check fails.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ALLOW = Path(__file__).with_name("site_probe_allow.toml")
# One page of each type. The key names the type in the report.
PAGES: dict[str, str] = {
    "home": "index.html",
    "understand-index": "understand/index.html",
    "understand-figures": "understand/reading-results.html",
    "understand-tables": "understand/what-it-computes.html",
    "get-started-index": "get-started/index.html",
    "get-started-install": "get-started/install.html",
    "staircase-step": "get-started/staircase/step1.html",
    "theory-index": "theory/index.html",
    "theory-maths": "theory/groundwater-flow.html",
    "theory-long": "theory/exits.html",
    "reference-index": "reference/index.html",
    "parameters-index": "reference/parameters/index.html",
    "parameters-section": "reference/parameters/domain.html",
    "parameters-explorer": "reference/parameters/explorer.html",
    "parameters-grammar": "reference/parameters/grammar.html",
    "python-class": "reference/python/Catalog.html",
    "cli-verb": "reference/cli/catalog.html",
    "catalog-solvers": "reference/solvers.html",
    "validation": "theory/validation.html",
    "contribute-index": "contribute/index.html",
    "contribute-handbook": "contribute/handbook.html",
    "about-cite": "about/cite.html",
    "search": "search.html",
}
SIZES = (390, 768, 961, 1024, 1100, 1200, 1280, 1440)
MOBILE = 390
# The bar is 80 px tall in one row. A second row of icons makes it 93 to 100 px.
HEADER_MAX = 84
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

MEASURE_OVERFLOW = """() => {
  const root = document.documentElement;
  const wide = root.scrollWidth - root.clientWidth;
  if (wide <= 1) return {wide: 0, offenders: []};
  const limit = root.clientWidth + 1;
  const scrolls = (el) => {
    for (let p = el.parentElement; p && p !== root; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true;
    }
    return false;
  };
  const offenders = [];
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.right <= limit || scrolls(el)) continue;
    if (getComputedStyle(el).position === 'fixed') continue;
    offenders.push({
      tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 60),
      right: Math.round(r.right), text: (el.textContent || '').trim().slice(0, 40),
    });
    if (offenders.length >= 5) break;
  }
  return {wide, offenders};
}"""

HEADER_HEIGHT = """() => {
  const h = document.querySelector('header.bd-header');
  return h ? Math.round(h.getBoundingClientRect().height) : -1;
}"""

SET_THEME = """(mode) => {
  document.documentElement.dataset.mode = mode;
  document.documentElement.dataset.theme = mode;
  try { localStorage.setItem('mode', mode); localStorage.setItem('theme', mode); } catch (e) {}
}"""


@dataclass
class Report:
    """The failures of a run, one line each."""

    failures: list[str] = field(default_factory=list)
    checked: int = 0

    def fail(self, page: str, text: str) -> None:
        self.failures.append(f"{page}: {text}")


def load_allow() -> list[dict[str, str]]:
    """Return the violations that are accepted, each with its reason."""
    if not ALLOW.exists():
        return []
    return tomllib.loads(ALLOW.read_text(encoding="utf-8")).get("allow", [])


def allowed(allow: list[dict[str, str]], page: str, rule: str, target: str) -> bool:
    """Tell whether a violation is in the allow list."""
    return any(
        a["rule"] == rule and a.get("page", page) == page and a.get("target", "") in target
        for a in allow
    )


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Keep the console for the report."""


def serve(site: Path) -> tuple[socketserver.TCPServer, int]:
    """Serve ``site`` on a free local port and return the server and the port."""
    handler = functools.partial(_Quiet, directory=str(site))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def probe(
    site: Path, axe: Path | None, chromium: str | None, names: list[str], json_out: Path | None
) -> int:
    """Run the checks on the named pages and return the exit code."""
    from playwright.sync_api import sync_playwright

    allow = load_allow()
    report = Report()
    results: dict[str, dict[str, object]] = {}
    server, port = serve(site)
    axe_source = axe.read_text(encoding="utf-8") if axe else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium, args=["--no-sandbox"])
        for name in names:
            path = PAGES[name]
            if not (site / path).exists():
                report.fail(name, f"the page {path} is not in the site")
                continue
            url = f"http://127.0.0.1:{port}/{path}"
            results[name] = check_page(browser, url, name, axe_source, allow, report)
            report.checked += 1
        browser.close()
    server.shutdown()
    if json_out:
        json_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for line in report.failures:
        print(line)
    print(f"{report.checked} page(s) probed, {len(report.failures)} problem(s)")
    return 1 if report.failures else 0


def check_page(browser, url: str, name: str, axe_source: str | None, allow, report: Report) -> dict:  # noqa: ANN001
    """Run every check on one page and return the measures."""
    measures: dict[str, object] = {}
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(url, wait_until="load")
    page.wait_for_timeout(300)
    heights = {}
    for width in SIZES:
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(100)
        heights[width] = page.evaluate(HEADER_HEIGHT)
        if width == MOBILE:
            over = page.evaluate(MEASURE_OVERFLOW)
            measures["overflow_px"] = over["wide"]
            if over["wide"]:
                report.fail(
                    name,
                    f"scrolls sideways by {over['wide']} px at {MOBILE} px: "
                    + "; ".join(
                        f"<{o['tag']} class={o['cls']!r}> right={o['right']}"
                        for o in over["offenders"]
                    ),
                )
    measures["header_px"] = heights
    for width, height in heights.items():
        if height > HEADER_MAX:
            report.fail(name, f"header is {height} px tall at {width} px (limit {HEADER_MAX})")
    if axe_source:
        page.set_viewport_size({"width": 1280, "height": 900})
        violations: dict[str, list[str]] = {}
        for mode in ("light", "dark"):
            page.evaluate(SET_THEME, mode)
            page.wait_for_timeout(150)
            page.evaluate(axe_source)
            result = page.evaluate(
                "tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", AXE_TAGS
            )
            for item in result["violations"]:
                targets = [", ".join(n["target"][-1:]) for n in item["nodes"]][:4]
                joined = " | ".join(targets)
                if allowed(allow, name, item["id"], joined):
                    continue
                violations.setdefault(f"{item['id']} ({item['impact']})", []).append(
                    f"{mode}: {len(item['nodes'])} node(s), e.g. {joined[:160]}"
                )
        measures["axe"] = {k: v for k, v in violations.items()}
        for rule, lines in violations.items():
            report.fail(name, f"axe {rule}: {'; '.join(lines)}")
    for message in errors:
        report.fail(name, f"script error: {message[:160]}")
    context.close()
    return measures


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the probe."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("site", type=Path, help="the built HTML folder")
    parser.add_argument("--axe", type=Path, default=None, help="path of axe.min.js")
    parser.add_argument(
        "--chromium", default=os.environ.get("HMP_CHROMIUM"), help="Chromium executable"
    )
    parser.add_argument("--pages", nargs="*", choices=sorted(PAGES), help="page types to probe")
    parser.add_argument("--no-axe", action="store_true", help="skip the accessibility check")
    parser.add_argument("--json", type=Path, default=None, help="write the measures here")
    args = parser.parse_args(argv)
    axe = None if args.no_axe else args.axe or Path("node_modules/axe-core/axe.min.js")
    if axe is not None and not axe.exists():
        parser.error(
            f"axe-core not found at {axe}: npm install axe-core, or pass --axe, or --no-axe"
        )
    return probe(args.site, axe, args.chromium, args.pages or list(PAGES), args.json)


if __name__ == "__main__":
    sys.exit(main())
