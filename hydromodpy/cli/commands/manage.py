"""``hmp manage`` - browser UI for workspace inspection and cleanup."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pandas as pd

from hydromodpy.cli.commands.delete import delete_simulation_artifacts
from hydromodpy.cli.helpers import EXIT_CONFIG, resolve_workspace
from hydromodpy.results.storage_contract import CATALOG_FILENAME, SIMULATIONS_DIRNAME
from hydromodpy.results.storage_diagnostics import (
    diagnose_result_storage,
    storage_artefact_basename,
    storage_artefact_kind,
)

NAME = "manage"
HELP = "Open a local browser UI to inspect DuckDB tables and manage simulations"

_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HydroModPy Workspace Manager</title>
  <style>
    :root {
      --bg: #f6f1e8;
      --panel: #fffdf9;
      --ink: #1d2730;
      --muted: #6a7680;
      --line: #d9d0c4;
      --accent: #0f6b6f;
      --accent-2: #b44f2b;
      --warn: #8f2d24;
      --chip: #e9f4f2;
      --shadow: 0 16px 36px rgba(34, 44, 52, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Aptos", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(15,107,111,0.08), transparent 26rem),
        linear-gradient(180deg, #f9f4eb 0%, var(--bg) 100%);
    }
    header {
      padding: 1.4rem 1.6rem 1rem;
      border-bottom: 1px solid rgba(29,39,48,0.08);
      backdrop-filter: blur(12px);
      background: rgba(246, 241, 232, 0.84);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      margin: 0 0 0.35rem;
      font-size: 1.55rem;
      letter-spacing: 0.01em;
    }
    p {
      margin: 0;
      color: var(--muted);
    }
    main {
      padding: 1.25rem;
      display: grid;
      gap: 1rem;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .section-head {
      padding: 1rem 1.1rem 0.8rem;
      border-bottom: 1px solid rgba(29,39,48,0.08);
      display: flex;
      flex-wrap: wrap;
      gap: 0.7rem;
      align-items: center;
      justify-content: space-between;
    }
    .section-head h2 {
      margin: 0;
      font-size: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
    }
    input, select, button {
      font: inherit;
      border-radius: 10px;
      border: 1px solid #c9beb2;
      padding: 0.55rem 0.7rem;
      background: #fff;
      color: var(--ink);
    }
    input, select {
      min-width: 12rem;
    }
    button {
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border-color: transparent;
      transition: transform 120ms ease, opacity 120ms ease;
    }
    button.secondary {
      background: #ddeceb;
      color: var(--accent);
    }
    button.warn {
      background: var(--accent-2);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
      transform: none;
    }
    button:hover:not(:disabled) {
      transform: translateY(-1px);
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
      gap: 0.75rem;
      padding: 1rem 1.1rem 1.1rem;
    }
    .card {
      border: 1px solid rgba(15,107,111,0.16);
      background: linear-gradient(180deg, #ffffff 0%, #f5fbfa 100%);
      border-radius: 14px;
      padding: 0.85rem 0.95rem;
    }
    .card .label {
      display: block;
      color: var(--muted);
      font-size: 0.8rem;
      margin-bottom: 0.35rem;
    }
    .card .value {
      font-weight: 700;
      font-size: 1.15rem;
    }
    .table-wrap {
      overflow: auto;
      max-height: 29rem;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }
    th, td {
      padding: 0.58rem 0.7rem;
      border-bottom: 1px solid rgba(29,39,48,0.08);
      vertical-align: top;
      text-align: left;
      white-space: nowrap;
    }
    td.wrap, th.wrap {
      white-space: normal;
      min-width: 14rem;
    }
    tbody tr:hover {
      background: rgba(15,107,111,0.05);
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
    }
    .chip {
      display: inline-flex;
      padding: 0.28rem 0.5rem;
      border-radius: 999px;
      background: var(--chip);
      color: var(--accent);
      font-size: 0.8rem;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 3.4rem;
      padding: 0.22rem 0.48rem;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .pill.OK {
      background: #dff1e6;
      color: #12643b;
    }
    .pill.WARN {
      background: #fff1cf;
      color: #856200;
    }
    .pill.KO {
      background: #f8dfdc;
      color: var(--warn);
    }
    .muted {
      color: var(--muted);
    }
    .status {
      padding: 0.7rem 1.1rem 1rem;
      color: var(--muted);
      min-height: 2.6rem;
    }
    .status.error {
      color: var(--warn);
    }
    .two-col {
      display: grid;
      gap: 1rem;
      grid-template-columns: 1.6fr 1fr;
    }
    code {
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 0.9em;
    }
    @media (max-width: 1100px) {
      .two-col { grid-template-columns: 1fr; }
      .table-wrap { max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>HydroModPy Workspace Manager</h1>
    <p id="workspace-path">Loading workspace...</p>
  </header>
  <main>
    <section>
      <div class="section-head">
        <h2>Workspace summary</h2>
        <div class="controls">
          <select id="workspace-select"></select>
          <button class="secondary" id="refresh-all">Refresh all</button>
        </div>
      </div>
      <div class="summary" id="summary-cards"></div>
    </section>

    <section>
      <div class="section-head">
        <h2>Result diagnostics</h2>
        <div class="controls">
          <button class="secondary" id="diag-refresh">Refresh diagnostics</button>
          <button class="warn" id="diag-clean">Delete selected cleanup paths</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Status</th>
              <th>Check</th>
              <th class="wrap">Detail</th>
              <th class="wrap">Hint</th>
              <th>Cleanup</th>
            </tr>
          </thead>
          <tbody id="diag-body"></tbody>
        </table>
      </div>
      <div class="status" id="diag-status"></div>
    </section>

    <div class="two-col">
      <section>
        <div class="section-head">
          <h2>Simulations</h2>
          <div class="controls">
            <input id="sim-filter" placeholder="Filter by name, project, solver, status">
            <button class="secondary" id="sim-select-visible">Select visible</button>
            <button class="warn" id="sim-delete">Delete selected</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Name</th>
                <th>Project</th>
                <th>Solver</th>
                <th>Status</th>
                <th>Total size</th>
                <th>Created</th>
                <th>sim_id</th>
              </tr>
            </thead>
            <tbody id="sim-body"></tbody>
          </table>
        </div>
        <div class="status" id="sim-status"></div>
      </section>

      <section>
        <div class="section-head">
          <h2>Orphan artefacts</h2>
          <div class="controls">
            <button class="secondary" id="orph-select-all">Select all</button>
            <button class="warn" id="orph-delete">Delete selected</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Kind</th>
                <th>Size</th>
                <th class="wrap">Path</th>
              </tr>
            </thead>
            <tbody id="orph-body"></tbody>
          </table>
        </div>
        <div class="status" id="orph-status"></div>
      </section>
    </div>

    <section>
      <div class="section-head">
        <h2>DuckDB table browser</h2>
        <div class="controls">
          <select id="db-select"></select>
          <select id="table-select"></select>
          <input id="preview-limit" type="number" min="10" max="500" value="100">
          <button class="secondary" id="preview-load">Load table</button>
        </div>
      </div>
      <div class="summary" style="padding-top: 0.7rem; padding-bottom: 0.7rem;">
        <div class="chips" id="table-chips"></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead id="preview-head"></thead>
          <tbody id="preview-body"></tbody>
        </table>
      </div>
      <div class="status" id="preview-status"></div>
    </section>
  </main>

  <script>
    const state = {
      currentWorkspace: null,
      workspaces: [],
      scanRoot: null,
      summary: null,
      simulations: [],
      orphans: [],
      diagnostics: [],
      tables: { catalog: [], cache: [] },
    };

    function formatBytes(bytes) {
      const value = Number(bytes || 0);
      if (!Number.isFinite(value) || value <= 0) return "0 B";
      const units = ["B", "KB", "MB", "GB", "TB"];
      let size = value;
      let idx = 0;
      while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx += 1;
      }
      return `${size.toFixed(size >= 100 || idx === 0 ? 0 : 1)} ${units[idx]}`;
    }

    function setStatus(id, message, isError = false) {
      const node = document.getElementById(id);
      node.textContent = message || "";
      node.className = isError ? "status error" : "status";
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    async function getJson(url) {
      const response = await fetch(url);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      return payload;
    }

    async function postJson(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      return payload;
    }

    function workspaceQuery() {
      if (!state.currentWorkspace) return "";
      return `workspace=${encodeURIComponent(state.currentWorkspace)}`;
    }

    function simulationMatches(row, query) {
      if (!query) return true;
      const haystack = [
        row.name,
        row.project,
        row.solver,
        row.status,
        row.sim_id,
      ].join(" ").toLowerCase();
      return haystack.includes(query.toLowerCase());
    }

    function renderSummary() {
      const cards = document.getElementById("summary-cards");
      if (!state.summary) {
        cards.innerHTML = "";
        return;
      }
      document.getElementById("workspace-path").textContent =
        `${state.summary.workspace_label} - ${state.summary.workspace}`;
      const entries = [
        ["Simulations", String(state.summary.simulation_count || 0)],
        ["Simulation artefacts", formatBytes(state.summary.simulation_bytes || 0)],
        ["Orphan artefacts", formatBytes(state.summary.orphan_bytes || 0)],
        ["Diagnostic warnings", String(state.summary.diagnostic_warning_count || 0)],
        ["Catalog", formatBytes(state.summary.catalog_bytes || 0)],
        ["Input cache", formatBytes(state.summary.cache_bytes || 0)],
      ];
      cards.innerHTML = entries.map(([label, value]) => `
        <div class="card">
          <span class="label">${label}</span>
          <span class="value">${value}</span>
        </div>
      `).join("");
    }

    function renderWorkspaceChoices() {
      const select = document.getElementById("workspace-select");
      select.innerHTML = state.workspaces.map((row) => `
        <option value="${row.id}">${row.label}</option>
      `).join("");
      if (state.currentWorkspace) {
        select.value = state.currentWorkspace;
      }
    }

    function renderSimulations() {
      const tbody = document.getElementById("sim-body");
      const query = document.getElementById("sim-filter").value.trim();
      const rows = state.simulations.filter((row) => simulationMatches(row, query));
      tbody.innerHTML = rows.map((row) => `
        <tr>
          <td><input type="checkbox" class="sim-check" value="${row.sim_id}"></td>
          <td>${row.name || "<span class='muted'>(no name)</span>"}</td>
          <td>${row.project || ""}</td>
          <td>${row.solver || ""}</td>
          <td>${row.status || ""}</td>
          <td>${formatBytes(row.total_bytes)}</td>
          <td>${row.created_at || ""}</td>
          <td><code>${row.sim_id}</code></td>
        </tr>
      `).join("");
      setStatus("sim-status", `${rows.length} simulation(s) shown.`);
    }

    function renderOrphans() {
      const tbody = document.getElementById("orph-body");
      tbody.innerHTML = state.orphans.map((row) => `
        <tr>
          <td><input type="checkbox" class="orph-check" value="${row.path}"></td>
          <td>${row.kind}</td>
          <td>${formatBytes(row.size_bytes)}</td>
          <td class="wrap"><code>${row.path}</code></td>
        </tr>
      `).join("");
      const total = state.orphans.reduce((acc, row) => acc + Number(row.size_bytes || 0), 0);
      setStatus("orph-status", `${state.orphans.length} orphan artefact(s), ${formatBytes(total)} total.`);
    }

    function renderDiagnostics() {
      const tbody = document.getElementById("diag-body");
      tbody.innerHTML = state.diagnostics.map((row) => {
        const paths = row.paths || [];
        const encodedPaths = encodeURIComponent(JSON.stringify(paths));
        const cleanupLabel = paths.length
          ? `${paths.length} path(s), ${formatBytes(row.cleanup_bytes || 0)}`
          : "";
        const disabled = paths.length ? "" : "disabled";
        return `
          <tr>
            <td><input type="checkbox" class="diag-check" data-paths="${encodedPaths}" ${disabled}></td>
            <td><span class="pill ${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
            <td><code>${escapeHtml(row.name)}</code></td>
            <td class="wrap">${escapeHtml(row.detail)}</td>
            <td class="wrap">${escapeHtml(row.hint || "")}</td>
            <td>${escapeHtml(cleanupLabel)}</td>
          </tr>
        `;
      }).join("");
      const warnings = state.diagnostics.filter((row) => row.status !== "OK").length;
      const cleanupCount = state.diagnostics.reduce(
        (acc, row) => acc + Number((row.paths || []).length),
        0
      );
      setStatus(
        "diag-status",
        `${state.diagnostics.length} diagnostic check(s), ${warnings} warning/error check(s), ${cleanupCount} cleanup path(s).`,
        warnings > 0
      );
    }

    function renderPreview(payload) {
      const thead = document.getElementById("preview-head");
      const tbody = document.getElementById("preview-body");
      const chips = document.getElementById("table-chips");
      const tables = state.tables[document.getElementById("db-select").value] || [];
      chips.innerHTML = tables.map((entry) => `<span class="chip">${entry.name} - ${entry.type}</span>`).join("");

      const columns = payload.columns || [];
      thead.innerHTML = `<tr>${columns.map((col) => `<th>${col}</th>`).join("")}</tr>`;
      tbody.innerHTML = (payload.rows || []).map((row) => {
        return `<tr>${columns.map((col) => `<td class="wrap">${row[col] == null ? "" : String(row[col])}</td>`).join("")}</tr>`;
      }).join("");
      setStatus(
        "preview-status",
        `${payload.database}: ${payload.table} - ${payload.row_count} row(s) shown.`
      );
    }

    async function loadWorkspaceList() {
      const payload = await getJson("/api/workspaces");
      state.scanRoot = payload.scan_root || null;
      state.workspaces = payload.workspaces || [];
      state.currentWorkspace = state.currentWorkspace || payload.default_workspace || null;
      renderWorkspaceChoices();
    }

    async function loadSummary() {
      state.summary = await getJson(`/api/summary?${workspaceQuery()}`);
      renderSummary();
    }

    async function loadSimulations() {
      const payload = await getJson(`/api/simulations?${workspaceQuery()}`);
      state.simulations = payload.rows || [];
      renderSimulations();
    }

    async function loadOrphans() {
      const payload = await getJson(`/api/orphans?${workspaceQuery()}`);
      state.orphans = payload.rows || [];
      renderOrphans();
    }

    async function loadDiagnostics() {
      const payload = await getJson(`/api/diagnostics?${workspaceQuery()}`);
      state.diagnostics = payload.rows || [];
      renderDiagnostics();
    }

    async function loadTables(database) {
      const payload = await getJson(
        `/api/tables?database=${encodeURIComponent(database)}&${workspaceQuery()}`
      );
      state.tables[database] = payload.tables || [];
      const select = document.getElementById("table-select");
      select.innerHTML = state.tables[database].map((entry) => `
        <option value="${entry.name}">${entry.name} (${entry.type})</option>
      `).join("");
      renderPreview({ database, table: "", columns: [], rows: [], row_count: 0 });
      if (state.tables[database].length) {
        await previewTable();
      } else {
        document.getElementById("preview-head").innerHTML = "";
        document.getElementById("preview-body").innerHTML = "";
        setStatus("preview-status", `${database}: no readable tables.`);
      }
    }

    async function previewTable() {
      const database = document.getElementById("db-select").value;
      const table = document.getElementById("table-select").value;
      const limit = document.getElementById("preview-limit").value || "100";
      if (!table) {
        setStatus("preview-status", `${database}: no table selected.`);
        return;
      }
      const payload = await getJson(
        `/api/preview?database=${encodeURIComponent(database)}&table=${encodeURIComponent(table)}&limit=${encodeURIComponent(limit)}&${workspaceQuery()}`
      );
      renderPreview(payload);
    }

    function checkedValues(selector) {
      return Array.from(document.querySelectorAll(selector))
        .filter((node) => node.checked)
        .map((node) => node.value);
    }

    function checkedDiagnosticPaths() {
      const paths = [];
      document.querySelectorAll(".diag-check").forEach((node) => {
        if (!node.checked || node.disabled) return;
        try {
          const decoded = JSON.parse(decodeURIComponent(node.dataset.paths || "[]"));
          decoded.forEach((path) => paths.push(path));
        } catch (error) {
          // Ignore malformed client-side state; the server still validates paths.
        }
      });
      return Array.from(new Set(paths));
    }

    async function deleteSelectedSimulations() {
      const simIds = checkedValues(".sim-check");
      if (!simIds.length) {
        setStatus("sim-status", "Select at least one simulation first.", true);
        return;
      }
      const ok = window.confirm(
        `Delete ${simIds.length} simulation(s)? This removes DuckDB rows and on-disk .zarr/.parquet artefacts.`
      );
      if (!ok) return;
      const payload = await postJson("/api/delete-simulations", {
        workspace: state.currentWorkspace,
        sim_ids: simIds,
      });
      setStatus(
        "sim-status",
        `Deleted ${payload.deleted.length} simulation(s), freed ${formatBytes(payload.freed_bytes)}.`
      );
      await Promise.all([loadSummary(), loadSimulations(), loadOrphans()]);
    }

    async function deleteSelectedOrphans() {
      const paths = checkedValues(".orph-check");
      if (!paths.length) {
        setStatus("orph-status", "Select at least one orphan artefact first.", true);
        return;
      }
      const ok = window.confirm(
        `Delete ${paths.length} orphan artefact(s)?`
      );
      if (!ok) return;
      const payload = await postJson("/api/delete-orphans", {
        workspace: state.currentWorkspace,
        paths,
      });
      setStatus(
        "orph-status",
        `Deleted ${payload.deleted.length} orphan artefact(s), freed ${formatBytes(payload.freed_bytes)}.`
      );
      await Promise.all([loadSummary(), loadOrphans()]);
    }

    async function deleteSelectedDiagnosticPaths() {
      const paths = checkedDiagnosticPaths();
      if (!paths.length) {
        setStatus("diag-status", "Select at least one diagnostic with cleanup paths first.", true);
        return;
      }
      const ok = window.confirm(
        `Delete ${paths.length} cleanup path(s)? Only files under simulations/ can be removed.`
      );
      if (!ok) return;
      const payload = await postJson("/api/delete-orphans", {
        workspace: state.currentWorkspace,
        paths,
      });
      setStatus(
        "diag-status",
        `Deleted ${payload.deleted.length} cleanup path(s), freed ${formatBytes(payload.freed_bytes)}.`
      );
      await Promise.all([loadSummary(), loadOrphans(), loadDiagnostics()]);
    }

    async function refreshAll() {
      try {
        await Promise.all([loadSummary(), loadSimulations(), loadOrphans(), loadDiagnostics()]);
        await loadTables(document.getElementById("db-select").value);
      } catch (error) {
        setStatus("preview-status", error.message, true);
      }
    }

    document.getElementById("refresh-all").addEventListener("click", refreshAll);
    document.getElementById("diag-refresh").addEventListener("click", async () => {
      try {
        await loadDiagnostics();
      } catch (error) {
        setStatus("diag-status", error.message, true);
      }
    });
    document.getElementById("diag-clean").addEventListener("click", async () => {
      try {
        await deleteSelectedDiagnosticPaths();
      } catch (error) {
        setStatus("diag-status", error.message, true);
      }
    });
    document.getElementById("workspace-select").addEventListener("change", async (event) => {
      state.currentWorkspace = event.target.value;
      try {
        await refreshAll();
      } catch (error) {
        setStatus("preview-status", error.message, true);
        setStatus("sim-status", error.message, true);
        setStatus("orph-status", error.message, true);
      }
    });
    document.getElementById("sim-filter").addEventListener("input", renderSimulations);
    document.getElementById("sim-select-visible").addEventListener("click", () => {
      document.querySelectorAll(".sim-check").forEach((node) => {
        node.checked = true;
      });
    });
    document.getElementById("sim-delete").addEventListener("click", async () => {
      try {
        await deleteSelectedSimulations();
      } catch (error) {
        setStatus("sim-status", error.message, true);
      }
    });
    document.getElementById("orph-select-all").addEventListener("click", () => {
      document.querySelectorAll(".orph-check").forEach((node) => {
        node.checked = true;
      });
    });
    document.getElementById("orph-delete").addEventListener("click", async () => {
      try {
        await deleteSelectedOrphans();
      } catch (error) {
        setStatus("orph-status", error.message, true);
      }
    });
    document.getElementById("db-select").addEventListener("change", async (event) => {
      try {
        await loadTables(event.target.value);
      } catch (error) {
        setStatus("preview-status", error.message, true);
      }
    });
    document.getElementById("preview-load").addEventListener("click", async () => {
      try {
        await previewTable();
      } catch (error) {
        setStatus("preview-status", error.message, true);
      }
    });

    async function boot() {
      document.getElementById("db-select").innerHTML = `
        <option value="catalog">catalog</option>
        <option value="cache">cache</option>
      `;
      await loadWorkspaceList();
      await refreshAll();
    }

    boot().catch((error) => {
      setStatus("preview-status", error.message, true);
      setStatus("sim-status", error.message, true);
      setStatus("orph-status", error.message, true);
    });
  </script>
</body>
</html>
"""


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Single workspace root to manage directly",
    )
    parser.add_argument(
        "--scan-root",
        default=None,
        help="Recursively discover every HydroModPy workspace under this root "
        "(default: current directory when --workspace is omitted)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Bind port (default: 0 for auto-assigned local port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser tab",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        print(
            "DuckDB is required for 'hmp manage'. Reinstall the project dependencies first: "
            "pip install -e .",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    workspace_arg = getattr(args, "workspace", None)
    scan_root_arg = getattr(args, "scan_root", None)
    if workspace_arg:
        workspace_root = resolve_workspace(workspace_arg)
        backend = _WorkspaceManagerBackend(workspace_root=workspace_root)
    else:
        scan_root = (
            Path(scan_root_arg).expanduser().resolve() if scan_root_arg else Path.cwd().resolve()
        )
        backend = _WorkspaceManagerBackend(scan_root=scan_root)
    server = ThreadingHTTPServer((args.host, args.port), _WorkspaceManagerHandler)
    server.backend = backend  # type: ignore[attr-defined]

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Workspace manager running at {url}")
    print(f"Discovered {len(backend.workspace_roots)} workspace(s).")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


class _WorkspaceManagerBackend:
    """Read and mutate one workspace in a browser-friendly shape."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        scan_root: Path | None = None,
    ) -> None:
        if workspace_root is not None:
            root = workspace_root.resolve()
            self.scan_root = root
            roots = [root]
        else:
            if scan_root is None:
                raise ValueError("scan_root is required when workspace_root is omitted")
            self.scan_root = scan_root.resolve()
            if not self.scan_root.is_dir():
                raise FileNotFoundError(f"Scan root does not exist: {self.scan_root}")
            roots = self._discover_workspaces(self.scan_root)
            if not roots:
                raise FileNotFoundError(
                    f"No HydroModPy workspace found under {self.scan_root} "
                    f"(missing {CATALOG_FILENAME} files)."
                )

        ordered = self._order_workspaces(roots)
        self.workspace_roots = {str(path): path for path in ordered}
        self.default_workspace = str(ordered[0])

    def list_workspaces(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for path in self.workspace_roots.values():
            rows.append(
                {
                    "id": str(path),
                    "path": str(path),
                    "label": _workspace_label(path, self.scan_root),
                    "catalog_exists": (path / CATALOG_FILENAME).is_file(),
                    "cache_exists": (path / "data" / "cache.duckdb").is_file(),
                }
            )
        return {
            "scan_root": str(self.scan_root),
            "default_workspace": self.default_workspace,
            "workspaces": rows,
        }

    def summary(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        simulations = self.list_simulations(workspace_ref)["rows"]
        orphans = self.list_orphans(workspace_ref)["rows"]
        diagnostics = self.result_diagnostics(workspace_ref)["rows"]
        catalog_path = workspace_root / CATALOG_FILENAME
        cache_path = workspace_root / "data" / "cache.duckdb"
        return {
            "workspace": str(workspace_root),
            "workspace_label": _workspace_label(workspace_root, self.scan_root),
            "scan_root": str(self.scan_root),
            "workspace_count": len(self.workspace_roots),
            "catalog_bytes": _path_size(catalog_path),
            "cache_bytes": _path_size(cache_path),
            "simulation_count": len(simulations),
            "simulation_bytes": sum(int(row["total_bytes"]) for row in simulations),
            "orphan_bytes": sum(int(row["size_bytes"]) for row in orphans),
            "diagnostic_warning_count": sum(1 for row in diagnostics if row.get("status") != "OK"),
        }

    def result_diagnostics(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        rows: list[dict[str, Any]] = []
        for diagnostic in diagnose_result_storage(workspace_root):
            record = dict(diagnostic.to_check())
            paths = [str(path) for path in record.get("paths", ()) or ()]
            record["paths"] = paths
            record["cleanup_count"] = len(paths)
            record["cleanup_bytes"] = sum(_path_size(Path(path)) for path in paths)
            rows.append(record)
        return {"rows": rows}

    def list_simulations(self, workspace_ref: str | None = None) -> dict[str, Any]:
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = self._resolve_workspace(workspace_ref)
        catalog_path = workspace_root / CATALOG_FILENAME
        if not catalog_path.exists():
            return {"rows": []}

        rows: list[dict[str, Any]] = []
        with SimulationCatalog(workspace_root) as catalog:
            df = catalog.list_simulations(order_by="created_at DESC")
            for _, raw in df.iterrows():
                record = {str(key): _json_value(value) for key, value in raw.items()}
                sim_id = str(record.get("sim_id", ""))
                zarr_path = catalog.zarr_path_for(sim_id)
                parquet_dir = catalog.parquet_dir_for(sim_id)
                zarr_bytes = _path_size(zarr_path)
                parquet_bytes = _path_size(parquet_dir)
                record.update(
                    {
                        "sim_id": sim_id,
                        "zarr_path": str(zarr_path),
                        "zarr_exists": zarr_path.exists(),
                        "zarr_bytes": zarr_bytes,
                        "parquet_dir": str(parquet_dir),
                        "parquet_exists": parquet_dir.exists(),
                        "parquet_bytes": parquet_bytes,
                        "total_bytes": zarr_bytes + parquet_bytes,
                    }
                )
                rows.append(record)
        return {"rows": rows}

    def delete_simulations(
        self,
        workspace_ref: str | None,
        sim_ids: list[str],
    ) -> dict[str, Any]:
        from hydromodpy.results.catalog import SimulationCatalog

        workspace_root = self._resolve_workspace(workspace_ref)
        deleted: list[dict[str, Any]] = []
        with SimulationCatalog(workspace_root) as catalog:
            for sim_id in sim_ids:
                run = catalog[sim_id]
                result = delete_simulation_artifacts(catalog, sim_id)
                deleted.append(
                    {
                        "sim_id": sim_id,
                        "name": run.name or sim_id,
                        "freed_bytes": int(result["freed_bytes"]),
                        "removed_paths": list(result["removed_paths"]),
                    }
                )
        return {
            "deleted": deleted,
            "freed_bytes": sum(int(item["freed_bytes"]) for item in deleted),
        }

    def list_orphans(self, workspace_ref: str | None = None) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        catalog_path = workspace_root / CATALOG_FILENAME
        simulations_dir = workspace_root / SIMULATIONS_DIRNAME
        registered: set[str] = set()
        if catalog_path.exists():
            from hydromodpy.results.catalog import SimulationCatalog

            with SimulationCatalog(workspace_root) as catalog:
                rows = catalog.connection.execute(
                    "SELECT CAST(sim_id AS VARCHAR) AS sim_id, storage_basename FROM simulations"
                ).fetchall()
                registered = {str(storage_basename) for _, storage_basename in rows}

        artefacts: list[dict[str, Any]] = []
        if not simulations_dir.is_dir():
            return {"rows": artefacts}

        for path in sorted(simulations_dir.iterdir()):
            if not (path.is_dir() or path.is_file()):
                continue
            kind = _artefact_kind(path)
            if kind is None:
                continue
            basename = _artefact_basename(path)
            if basename in registered:
                continue
            artefacts.append(
                {
                    "path": str(path),
                    "basename": basename,
                    "kind": kind,
                    "size_bytes": _path_size(path),
                }
            )
        return {"rows": artefacts}

    def delete_orphans(
        self,
        workspace_ref: str | None,
        paths: list[str],
    ) -> dict[str, Any]:
        workspace_root = self._resolve_workspace(workspace_ref)
        simulations_dir = workspace_root / SIMULATIONS_DIRNAME
        deleted: list[dict[str, Any]] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if not _is_relative_to(path, simulations_dir):
                raise ValueError(f"Refusing to delete outside simulations/: {path}")
            if not path.exists():
                continue
            freed_bytes = _path_size(path)
            if path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            deleted.append({"path": str(path), "freed_bytes": freed_bytes})
        return {
            "deleted": deleted,
            "freed_bytes": sum(int(item["freed_bytes"]) for item in deleted),
        }

    def list_tables(self, workspace_ref: str | None, database: str) -> dict[str, Any]:
        db_path = self._db_path(self._resolve_workspace(workspace_ref), database)
        if not db_path.exists():
            return {"database": database, "tables": []}

        import duckdb

        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = conn.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_type, table_name"
            ).fetchall()
        finally:
            conn.close()
        return {
            "database": database,
            "tables": [{"name": str(name), "type": str(table_type)} for name, table_type in rows],
        }

    def preview_table(
        self,
        workspace_ref: str | None,
        database: str,
        table: str,
        limit: int,
    ) -> dict[str, Any]:
        db_path = self._db_path(self._resolve_workspace(workspace_ref), database)
        if not db_path.exists():
            raise FileNotFoundError(f"No {database} database at {db_path}")

        limit = max(10, min(int(limit), 500))
        allowed = {entry["name"] for entry in self.list_tables(workspace_ref, database)["tables"]}
        if table not in allowed:
            raise ValueError(f"Unknown table '{table}' in {database}")

        import duckdb

        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            df = conn.execute(
                f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}" LIMIT {limit}'
            ).fetchdf()
        finally:
            conn.close()
        rows = [
            {str(column): _json_value(value) for column, value in row.items()}
            for row in df.to_dict(orient="records")
        ]
        return {
            "database": database,
            "table": table,
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(rows),
        }

    def _resolve_workspace(self, workspace_ref: str | None) -> Path:
        key = str(workspace_ref or self.default_workspace)
        try:
            return self.workspace_roots[key]
        except KeyError as exc:
            raise ValueError(f"Unknown workspace '{key}'") from exc

    def _db_path(self, workspace_root: Path, database: str) -> Path:
        if database == "catalog":
            return workspace_root / CATALOG_FILENAME
        if database == "cache":
            return workspace_root / "data" / "cache.duckdb"
        raise ValueError(f"Unsupported database '{database}'")

    @staticmethod
    def _discover_workspaces(scan_root: Path) -> list[Path]:
        roots = {
            path.parent.resolve() for path in scan_root.rglob(CATALOG_FILENAME) if path.is_file()
        }
        return sorted(roots)

    def _order_workspaces(self, roots: list[Path]) -> list[Path]:
        examples_root = (self.scan_root / "examples").resolve()

        def sort_key(path: Path) -> tuple[int, int, str]:
            path_str = str(path).lower()
            is_examples = 0 if path == examples_root else 1
            is_tmp = 1 if "\\tmp\\" in path_str or path_str.endswith("\\tmp") else 0
            return (is_examples, is_tmp, _workspace_label(path, self.scan_root).lower())

        return sorted(roots, key=sort_key)


class _WorkspaceManagerHandler(BaseHTTPRequestHandler):
    """Serve one small HTML app and a handful of JSON endpoints."""

    server_version = "HydroModPyManage/1.0"

    @property
    def backend(self) -> _WorkspaceManagerBackend:
        return self.server.backend  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._write_html(_HTML)
            return
        if parsed.path == "/api/workspaces":
            self._write_json(200, self.backend.list_workspaces())
            return
        query = parse_qs(parsed.query)
        workspace_ref = query.get("workspace", [None])[0]
        if parsed.path == "/api/summary":
            self._write_json(200, self.backend.summary(workspace_ref))
            return
        if parsed.path == "/api/simulations":
            self._write_json(200, self.backend.list_simulations(workspace_ref))
            return
        if parsed.path == "/api/orphans":
            self._write_json(200, self.backend.list_orphans(workspace_ref))
            return
        if parsed.path == "/api/diagnostics":
            self._write_json(200, self.backend.result_diagnostics(workspace_ref))
            return
        if parsed.path == "/api/tables":
            database = query.get("database", ["catalog"])[0]
            self._write_json(200, self.backend.list_tables(workspace_ref, database))
            return
        if parsed.path == "/api/preview":
            database = query.get("database", ["catalog"])[0]
            table = query.get("table", [""])[0]
            limit = int(query.get("limit", ["100"])[0])
            try:
                payload = self.backend.preview_table(workspace_ref, database, table, limit)
            except Exception as exc:
                self._write_json(400, {"error": str(exc)})
                return
            self._write_json(200, payload)
            return
        self._write_json(404, {"error": f"Unknown route: {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
        except Exception as exc:
            self._write_json(400, {"error": f"Invalid JSON body: {exc}"})
            return

        try:
            if parsed.path == "/api/delete-simulations":
                sim_ids = [str(item) for item in payload.get("sim_ids", []) if str(item).strip()]
                workspace_ref = payload.get("workspace")
                self._write_json(
                    200,
                    self.backend.delete_simulations(
                        str(workspace_ref) if workspace_ref is not None else None,
                        sim_ids,
                    ),
                )
                return
            if parsed.path == "/api/delete-orphans":
                paths = [str(item) for item in payload.get("paths", []) if str(item).strip()]
                workspace_ref = payload.get("workspace")
                self._write_json(
                    200,
                    self.backend.delete_orphans(
                        str(workspace_ref) if workspace_ref is not None else None,
                        paths,
                    ),
                )
                return
        except Exception as exc:
            self._write_json(400, {"error": str(exc)})
            return

        self._write_json(404, {"error": f"Unknown route: {parsed.path}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _write_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0

    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += int(child.stat().st_size)
            except OSError:
                continue
    except OSError:
        return total
    return total


def _artefact_kind(path: Path) -> str | None:
    return storage_artefact_kind(path)


def _artefact_basename(path: Path) -> str:
    return storage_artefact_basename(path)


def _workspace_label(path: Path, scan_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(scan_root.resolve())
        if str(rel) == ".":
            return path.resolve().name or str(path.resolve())
        return str(rel)
    except ValueError:
        return str(path.resolve())


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path | UUID):
        return str(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            scalar = value.item()
        except Exception:
            scalar = None
        if scalar is not None and scalar is not value:
            return _json_value(scalar)
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
