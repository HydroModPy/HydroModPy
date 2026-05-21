"""CSS used by the rendered network/transient HTML page."""

from __future__ import annotations

PAGE_CSS = """\
:root {
  color-scheme: light;
  --fg: #1f2933;
  --muted: #5d6875;
  --line: #d7dde5;
  --soft: #f4f7fa;
  --blue: #2662a5;
  --green: #26826a;
  --red: #b5413c;
  --orange: #b66a1f;
}
body {
  margin: 0;
  font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--fg);
  background: #ffffff;
}
header {
  padding: 24px 30px 16px;
  border-bottom: 1px solid var(--line);
}
main {
  padding: 18px 30px 34px;
  display: grid;
  gap: 22px;
}
h1, h2, h3 { margin: 0; line-height: 1.2; }
h1 { font-size: 25px; }
h2 { font-size: 19px; }
h3 { font-size: 15px; margin-bottom: 8px; }
p { margin: 7px 0 0; color: var(--muted); }
code { background: #eef2f5; padding: 1px 4px; border-radius: 4px; }
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 7px 8px;
  text-align: right;
  white-space: nowrap;
}
th:first-child, td:first-child { text-align: left; }
th { background: var(--soft); font-weight: 650; color: #2c3744; }
.lead { max-width: 1050px; font-size: 15px; }
.equation {
  margin-top: 12px;
  padding: 10px 12px;
  background: var(--soft);
  border-left: 4px solid var(--blue);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #26313d;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(285px, 1fr));
  gap: 16px;
  align-items: start;
}
.wide-grid {
  display: grid;
  grid-template-columns: minmax(330px, 0.85fr) minmax(460px, 1.15fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 920px) { .wide-grid { grid-template-columns: 1fr; } }
.panel {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 14px;
  overflow-x: auto;
}
.metric-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 10px;
}
.metric {
  border-left: 3px solid var(--blue);
  background: var(--soft);
  padding: 7px 9px;
}
.metric span { display: block; color: var(--muted); font-size: 12px; }
.metric strong { font-size: 15px; }
.figure-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
  align-items: start;
  margin-top: 12px;
}
.figure-card {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  background: #fff;
}
.figure-card img {
  display: block;
  width: 100%;
  height: auto;
}
.caption {
  color: var(--muted);
  font-size: 12px;
  margin-top: 7px;
}
.note { color: var(--muted); font-size: 12px; margin-top: 8px; }
.muted { color: var(--muted); }
svg { max-width: 100%; height: auto; }
"""
