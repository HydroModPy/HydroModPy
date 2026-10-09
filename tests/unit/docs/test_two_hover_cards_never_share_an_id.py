"""The {toml} links and the glossary terms each get a hover card with an id of their own.

hmp.js builds one card element per ``hoverCard`` instance. Two instances on a page
(the glossary page has both kinds of link) used to give both cards ``id="hmp-hover"``,
so ``aria-describedby`` pointed at the wrong element for the second. The script runs
under node against a small stand-in for the DOM. The test is skipped without node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "docs" / "source" / "_static" / "hmp.js"

DRIVER = r"""
const fs = require("fs");
const listeners = {};
const made = [];
function node(tag) {
  return {
    tag, children: [], attrs: {}, style: {}, dataset: {}, hidden: false, className: "", id: "",
    classList: { contains: () => false },
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute() {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {},
    getBoundingClientRect: () => ({ bottom: 0, left: 0 }),
    offsetWidth: 10,
    set textContent(v) { if (v === "") this.children = []; else this.text = v; },
  };
}
global.document = {
  documentElement: { dataset: {}, clientWidth: 800 },
  body: node("body"),
  createElement(tag) { const n = node(tag); made.push(n); return n; },
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
};
global.window = {
  matchMedia: () => ({ matches: false }), scrollX: 0, scrollY: 0, isSecureContext: false,
  addEventListener() {},
};
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
global.location = { hash: "" };
global.DOCUMENTATION_OPTIONS = { URL_ROOT: "" };
eval(fs.readFileSync(process.argv[2], "utf8"));

function link(cls) {
  const l = node("a");
  l.closest = (sel) => (sel === cls ? l : null);
  l.getAttribute = () => "";
  l.title = "";
  return l;
}
const entry = { p: "x", s: "y" };
window.hmpHoverCard("a.one", () => entry);
window.hmpHoverCard("a.two", () => entry);
window.hmpHoverCard("a.three", () => entry, "chosen-id");
const links = [link("a.one"), link("a.two"), link("a.three")];
(async () => {
  for (const l of links) {
    listeners.mouseover.forEach((fn) => fn({ target: l }));
    await new Promise((r) => setTimeout(r, 20));
  }
  const cards = made.filter((n) => n.className === "hmp-hover").map((n) => n.id);
  console.log(JSON.stringify({ cards, described: links.map((l) => l.attrs["aria-describedby"]) }));
})();
"""


@pytest.mark.allow_subprocess
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_each_card_has_its_own_id_and_the_link_points_at_it(tmp_path: Path) -> None:
    driver = tmp_path / "driver.js"
    driver.write_text(DRIVER, encoding="utf-8")
    done = subprocess.run(
        ["node", str(driver), str(SCRIPT)], capture_output=True, text=True, timeout=60, check=True
    )
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert len(set(seen["cards"])) == 3, seen
    assert seen["cards"][2] == "chosen-id"
    assert seen["described"] == seen["cards"]
