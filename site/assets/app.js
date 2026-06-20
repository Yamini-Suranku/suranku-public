const STORAGE_KEY = "dip-portal-state-v1";

const state = {
  domains: [],
  contracts: [],
  events: [],
  runs: [],
  catalogs: [],
  dataLineage: [],
  processLineage: [],
  staticMode: false
};

const $ = (selector) => document.querySelector(selector);

// Escape untrusted values before injecting into innerHTML.
function esc(value) {
  return String(value === undefined || value === null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const rid = (prefix) => `${prefix}_${Math.random().toString(16).slice(2, 14)}`;

const demoSeed = {
  domains: [
    { id: "commerce", name: "Retail Commerce", owner: "Commerce Data Office", description: "Retail orders, payments, and shipment events used for the demo data platform." }
  ],
  contracts: [
    { id: "commerce.orders.created.v1", domain_id: "commerce", topic: "commerce.orders.created", event_name: "orders_created", version: "v1", primary_keys: ["order_id"], description: "Order creation event published by the retail order service.", schema: 'syntax = "proto3";\n\nmessage OrderCreated {\n  string event_id = 1;\n  string order_id = 2;\n  string customer_id = 3;\n  double order_total = 4;\n}' },
    { id: "commerce.payments.captured.v1", domain_id: "commerce", topic: "commerce.payments.captured", event_name: "payments_captured", version: "v1", primary_keys: ["payment_id"], description: "Payment capture event published by the payment service.", schema: 'syntax = "proto3";\n\nmessage PaymentCaptured {\n  string event_id = 1;\n  string payment_id = 2;\n  string order_id = 3;\n  double amount = 4;\n}' },
    { id: "commerce.shipments.updated.v1", domain_id: "commerce", topic: "commerce.shipments.updated", event_name: "shipments_updated", version: "v1", primary_keys: ["shipment_id"], description: "Shipment status event published by the fulfillment service.", schema: 'syntax = "proto3";\n\nmessage ShipmentUpdated {\n  string event_id = 1;\n  string shipment_id = 2;\n  string order_id = 3;\n  string shipment_status = 4;\n}' }
  ]
};

function clone(value) { return JSON.parse(JSON.stringify(value)); }

/* -------------------------------------------------- static-mode persistence */

function saveStatic() {
  if (!state.staticMode) return;
  const snapshot = {};
  ["domains", "contracts", "events", "runs", "catalogs", "dataLineage", "processLineage"].forEach((k) => { snapshot[k] = state[k]; });
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot)); } catch (_) { /* ignore quota */ }
}

function staticReset() {
  state.domains = clone(demoSeed.domains);
  state.contracts = clone(demoSeed.contracts);
  state.events = [];
  state.runs = [];
  state.catalogs = [];
  state.dataLineage = [];
  state.processLineage = [];
  saveStatic();
}

function loadStatic() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch (_) { stored = null; }
  if (stored && Array.isArray(stored.contracts)) {
    Object.assign(state, stored);
  } else {
    staticReset();
  }
}

/* ---------------------------------------------------- static ingestion logic */

function staticIngestRecords(contract, records, markerId) {
  const keys = contract.primary_keys || [];
  const seen = new Set();
  const deduped = [];
  records.forEach((record) => {
    const key = JSON.stringify(keys.map((k) => record[k]));
    if (seen.has(key)) return;
    seen.add(key);
    deduped.push(record);
  });
  const runId = rid("run");
  ["intraday", "endofday", "analytics"].forEach((layer) => {
    const tableId = `${layer}.${contract.domain_id}.${contract.event_name}`;
    state.catalogs = state.catalogs.filter((c) => c.id !== tableId);
    state.catalogs.push({ id: tableId, layer, domain_id: contract.domain_id, table_name: contract.event_name, source_contract_id: contract.id, storage_path: `data/object-store/${layer}/${contract.domain_id}/${contract.event_name}/${runId}.parquet.jsonl`, record_count: deduped.length, updated_at: new Date().toISOString() });
    state.dataLineage.push({ id: rid("lin"), source: contract.topic, target: tableId, relation: "ingested_to", contract_id: contract.id, run_id: runId });
  });
  state.runs.unshift({ id: runId, marker_id: markerId, contract_id: contract.id, status: "completed", records_read: records.length, records_written: deduped.length, records_deduped: records.length - deduped.length, output_path: `data/object-store/analytics/${contract.domain_id}/${contract.event_name}/${runId}.parquet.jsonl` });
  [["marker_discovered", `Marker ${markerId} announced ${contract.topic}`], ["records_deduplicated", `${records.length - deduped.length} duplicate records removed by ${keys.join(", ")}`], ["catalogs_written", "intraday, endofday, and analytics layers updated"]].forEach(([step, detail]) => {
    state.processLineage.push({ id: rid("pl"), marker_id: markerId, run_id: runId, step_name: step, detail });
  });
  return { run_id: runId, contract_id: contract.id, records_read: records.length, records_written: deduped.length, records_deduped: records.length - deduped.length };
}

function staticIngestAll() {
  const markerId = `manual-${Math.random().toString(16).slice(2, 10)}`;
  const summaries = [];
  state.contracts.forEach((contract) => {
    const records = state.events.filter((e) => e.contract_id === contract.id).map((e) => e.payload);
    if (records.length) summaries.push(staticIngestRecords(contract, records, markerId));
  });
  if (!summaries.length) throw new Error("No contracts have events yet. Add events, then run ingestion.");
  return { marker_id: markerId, runs: summaries };
}

function staticRunDemoIngestion() {
  const demoEvents = {
    "commerce.orders.created.v1": [{ order_id: "o1" }, { order_id: "o1" }, { order_id: "o2" }],
    "commerce.payments.captured.v1": [{ payment_id: "p1" }, { payment_id: "p2" }],
    "commerce.shipments.updated.v1": [{ shipment_id: "s1" }, { shipment_id: "s2" }]
  };
  const markerId = "commerce-batch-001";
  const summaries = [];
  state.contracts.forEach((contract) => {
    const records = demoEvents[contract.id];
    if (records) summaries.push(staticIngestRecords(contract, records, markerId));
  });
  return { marker_id: markerId, runs: summaries };
}

function slug(text) { return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || rid("id"); }

/* --------------------------------------------------------------- api router */

async function api(path, options = {}) {
  if (state.staticMode) return staticApi(path, options);
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error((await response.text()) || `Request failed: ${path}`);
  return response.json();
}

function staticApi(path, options = {}) {
  const body = options.body ? JSON.parse(options.body) : {};
  if (path.startsWith("/api/lineage/columns")) return [];
  if (path.startsWith("/api/scan")) {
    if (path === "/api/scan/sources" && options.method !== "POST") return [];
    throw new Error("Scanning requires the FastAPI backend — not available in the static demo.");
  }
  switch (path) {
    case "/api/demo/reset": staticReset(); return { status: "reset", domains: state.domains.length, contracts: state.contracts.length };
    case "/api/ingestion-runs/demo": { const r = staticRunDemoIngestion(); saveStatic(); return r; }
    case "/api/ingestion-runs": {
      if (options.method === "POST") { const r = staticIngestAll(); saveStatic(); return r; }
      return state.runs;
    }
    case "/api/domains": {
      if (options.method === "POST") { const id = body.id || slug(body.name); state.domains = state.domains.filter((d) => d.id !== id); state.domains.push({ id, name: body.name, owner: body.owner || "", description: body.description || "" }); saveStatic(); return state.domains.at(-1); }
      return state.domains;
    }
    case "/api/contracts": {
      if (options.method === "POST") { const id = `${body.domain_id}.${body.event_name}.${body.version || "v1"}`; if (!state.domains.some((d) => d.id === body.domain_id)) state.domains.push({ id: body.domain_id, name: body.domain_id, owner: "", description: "" }); state.contracts = state.contracts.filter((c) => c.id !== id); state.contracts.push({ id, domain_id: body.domain_id, source_type: body.source_type || "kafka", topic: body.topic, event_name: body.event_name, version: body.version || "v1", primary_keys: body.primary_keys || [], description: body.description || "", schema: body.schema_text || "" }); saveStatic(); return state.contracts.at(-1); }
      return state.contracts;
    }
    case "/api/events": {
      if (options.method === "POST") { (body.records || []).forEach((rec) => state.events.push({ id: rid("ev"), contract_id: body.contract_id, payload: rec })); saveStatic(); return { contract_id: body.contract_id, added: (body.records || []).length }; }
      return state.events;
    }
    case "/api/lineage/data": {
      if (options.method === "POST") { state.dataLineage.push({ id: rid("lin"), source: body.source, target: body.target, relation: body.relation || "derived_from" }); saveStatic(); return state.dataLineage.at(-1); }
      return state.dataLineage;
    }
    case "/api/lineage/process": {
      if (options.method === "POST") { state.processLineage.push({ id: rid("pl"), marker_id: body.marker_id, run_id: body.run_id, step_name: body.step_name, detail: body.detail || "" }); saveStatic(); return state.processLineage.at(-1); }
      return state.processLineage;
    }
    case "/api/catalogs": return state.catalogs;
    default: throw new Error(`Unsupported static endpoint: ${path}`);
  }
}

function staticChat(question) {
  const q = question.toLowerCase();
  let answer = "This GitHub Pages demo runs fully in the browser. The Docker/FastAPI version adds persistent SQLite metadata, the authoring API, and self-monitoring.";
  if (q.includes("lineage")) answer = "Data lineage connects Kafka topics to intraday, endofday, and analytics catalog tables. Process lineage records marker discovery, deduplication, and catalog writes.";
  else if (q.includes("dedup") || q.includes("primary")) answer = "Deduplication uses each contract's declared primary keys to drop repeated events before they reach the catalog layers.";
  else if (q.includes("catalog") || q.includes("iceberg")) answer = "The template models intraday, endofday, and analytics catalogs. The Pages demo simulates them; the backend persists them in SQLite.";
  return { mode: "github-pages-demo", answer, sources: ["browser demo seed", "agent context"] };
}

/* --------------------------------------------------------------- rendering */

function card(title, body, meta = "") {
  return `<article class="card"><h3>${esc(title)}</h3><p>${esc(body)}</p>${meta ? `<div class="meta">${esc(meta)}</div>` : ""}</article>`;
}

function renderMetrics() {
  $("#domain-count").textContent = state.domains.length;
  $("#contract-count").textContent = state.contracts.length;
  $("#run-count").textContent = state.runs.length;
  $("#catalog-count").textContent = state.catalogs.length;
}

function renderDomains() {
  $("#domains-list").innerHTML = state.domains.length ? state.domains.map((d) => card(d.name || d.id, d.description || "—", `Owner: ${d.owner || "—"}`)).join("") : card("No domains yet", "Define one in the Build tab.");
}

function renderContracts() {
  $("#contracts-list").innerHTML = state.contracts.length ? state.contracts.map((c) =>
    `<article class="card">
      <h3>${esc(c.topic)}</h3>
      <p>${esc(c.description)}</p>
      <div class="meta">Event: ${esc(c.event_name)} | Version: ${esc(c.version)} | Primary keys: ${esc((c.primary_keys || []).join(", "))}</div>
      ${c.schema ? `<pre>${esc(c.schema)}</pre>` : ""}
    </article>`).join("") : card("No contracts yet", "Define one in the Build tab.");
}

function renderRuns() {
  $("#runs-list").innerHTML = state.runs.length ? state.runs.map((run) =>
    card(run.id, `${run.status}: ${run.records_written} written, ${run.records_deduped} deduped, ${run.records_read} read.`, `Marker: ${run.marker_id} | Output: ${run.output_path}`)).join("") : card("No ingestion runs yet", "Add events, then Run ingestion.");
}

function renderCatalogs() {
  $("#catalogs-list").innerHTML = state.catalogs.length ? state.catalogs.map((t) =>
    card(t.id, `${t.record_count} records at ${t.storage_path}`, `Source: ${t.source_contract_id}`)).join("") : card("No catalog tables yet", "Run ingestion to create catalog entries.");
}

function renderLineageLists() {
  $("#data-lineage-list").innerHTML = state.dataLineage.length ? state.dataLineage.map((e) =>
    card(e.relation, `${e.source} → ${e.target}`, e.run_id ? `Run: ${e.run_id}` : "manual")).join("") : card("No data lineage yet", "Run ingestion or add an edge.");
  $("#process-lineage-list").innerHTML = state.processLineage.length ? state.processLineage.map((s) =>
    card(s.step_name, s.detail, `Marker: ${s.marker_id} | Run: ${s.run_id}`)).join("") : card("No process lineage yet", "Run ingestion or add a step.");
}

function renderBuildOptions() {
  const dl = $("#domain-options");
  if (dl) dl.innerHTML = state.domains.map((d) => `<option value="${esc(d.id)}">`).join("");
  const sel = $("#events-contract");
  if (sel) sel.innerHTML = state.contracts.length ? state.contracts.map((c) => `<option value="${esc(c.id)}">${esc(c.id)}</option>`).join("") : `<option value="">Define a contract first</option>`;
  const mode = $("#build-mode");
  if (mode) mode.textContent = `Storage: ${state.staticMode ? "browser (localStorage)" : "backend (SQLite)"}`;
}

function renderAll() {
  renderMetrics();
  renderDomains();
  renderContracts();
  renderRuns();
  renderCatalogs();
  renderLineageLists();
  renderBuildOptions();
  if ($("#graph").classList.contains("active")) renderGraphs();
}

/* ------------------------------------------------------------------ refresh */

async function refresh() {
  try {
    const [domains, contracts, runs, catalogs, dataLineage, processLineage] = await Promise.all([
      api("/api/domains"), api("/api/contracts"), api("/api/ingestion-runs"),
      api("/api/catalogs"), api("/api/lineage/data"), api("/api/lineage/process")
    ]);
    Object.assign(state, { domains, contracts, runs, catalogs, dataLineage, processLineage });
  } catch (_) {
    state.staticMode = true;
    loadStatic();
  }
  renderAll();
}

/* --------------------------------------------------------------- build forms */

function setBuildStatus(message, ok = true) {
  const el = $("#build-status");
  el.hidden = false;
  el.textContent = message;
  el.style.color = ok ? "#047857" : "#b91c1c";
}

function formData(form) {
  const obj = {};
  new FormData(form).forEach((v, k) => { obj[k] = v; });
  return obj;
}

function wireBuildForms() {
  $("#domain-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    try { await api("/api/domains", { method: "POST", body: JSON.stringify(d) }); e.target.reset(); await refresh(); setBuildStatus(`Domain "${d.name}" added.`); }
    catch (err) { setBuildStatus(err.message, false); }
  });

  // Source type toggle: relational sources hide Protobuf and relabel fields.
  const sourceType = $("#source-type");
  function applySourceType() {
    const relational = sourceType.value === "relational";
    $("#topic-label").textContent = relational ? "Table (schema.table)" : "Kafka topic";
    $("#topic-input").placeholder = relational ? "public.orders" : "commerce.orders.created";
    $("#pk-label").textContent = relational ? "Primary keys (optional)" : "Primary keys (comma-separated)";
    $("#proto-fields").hidden = relational;
  }
  if (sourceType) { sourceType.addEventListener("change", applySourceType); applySourceType(); }

  $("#contract-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const source_type = d.source_type || "kafka";
    const payload = { domain_id: d.domain_id, source_type, topic: d.topic, event_name: d.event_name, version: d.version || "v1", primary_keys: (d.primary_keys || "").split(",").map((s) => s.trim()).filter(Boolean), schema_text: d.schema_text || "", description: d.description || "" };
    if (source_type === "kafka" && !payload.primary_keys.length) { setBuildStatus("At least one primary key is required for a Kafka source.", false); return; }
    if (!payload.topic.trim()) { setBuildStatus(source_type === "relational" ? "A table is required." : "A Kafka topic is required.", false); return; }
    try { await api("/api/contracts", { method: "POST", body: JSON.stringify(payload) }); e.target.reset(); applySourceType(); await refresh(); setBuildStatus(`Source "${payload.topic}" added.`); }
    catch (err) { setBuildStatus(err.message, false); }
  });

  $("#proto-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { $("#contract-form").querySelector('[name="schema_text"]').value = reader.result; };
    reader.readAsText(file);
  });

  $("#events-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    let records;
    try { records = JSON.parse(d.records); if (!Array.isArray(records)) throw new Error("Records must be a JSON array."); }
    catch (err) { setBuildStatus(`Invalid JSON: ${err.message}`, false); return; }
    try { const r = await api("/api/events", { method: "POST", body: JSON.stringify({ contract_id: d.contract_id, records }) }); e.target.reset(); await refresh(); setBuildStatus(`${r.added} events added to ${d.contract_id}.`); }
    catch (err) { setBuildStatus(err.message, false); }
  });

  $("#data-lineage-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    try { await api("/api/lineage/data", { method: "POST", body: JSON.stringify(d) }); e.target.reset(); await refresh(); setBuildStatus("Data lineage edge added."); }
    catch (err) { setBuildStatus(err.message, false); }
  });

  $("#process-lineage-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    try { await api("/api/lineage/process", { method: "POST", body: JSON.stringify(d) }); e.target.reset(); await refresh(); setBuildStatus("Process lineage step added."); }
    catch (err) { setBuildStatus(err.message, false); }
  });

  $("#import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { $("#import-json").value = reader.result; };
    reader.readAsText(file);
  });

  $("#import-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    let bundle;
    try { bundle = JSON.parse($("#import-json").value); }
    catch (err) { setBuildStatus(`Invalid JSON: ${err.message}`, false); return; }
    try {
      let count = 0;
      for (const dom of bundle.domains || []) { await api("/api/domains", { method: "POST", body: JSON.stringify(dom) }); count++; }
      for (const c of bundle.contracts || []) { await api("/api/contracts", { method: "POST", body: JSON.stringify({ ...c, primary_keys: c.primary_keys || [], schema_text: c.schema_text || c.schema || "" }) }); count++; }
      for (const ev of bundle.events || []) { await api("/api/events", { method: "POST", body: JSON.stringify(ev) }); count++; }
      for (const l of bundle.dataLineage || []) { await api("/api/lineage/data", { method: "POST", body: JSON.stringify(l) }); count++; }
      for (const p of bundle.processLineage || []) { await api("/api/lineage/process", { method: "POST", body: JSON.stringify(p) }); count++; }
      e.target.reset(); await refresh(); setBuildStatus(`Imported ${count} item(s).`);
    } catch (err) { setBuildStatus(err.message, false); }
  });
}

/* ------------------------------------------------------------------- D3 graphs */

let tooltipEl;
function showTip(html, x, y) { tooltipEl.hidden = false; tooltipEl.innerHTML = html; tooltipEl.style.left = `${x + 14}px`; tooltipEl.style.top = `${y + 14}px`; }
function hideTip() { tooltipEl.hidden = true; }

const LAYER_COLOR = { topic: "#1767aa", intraday: "#0ea5e9", endofday: "#7c3aed", analytics: "#059669", marker: "#145184", run: "#1767aa", step: "#94a3b8" };

function nodeType(id, kind) {
  if (kind) return kind;
  const layer = String(id).split(".")[0];
  return ["intraday", "endofday", "analytics"].includes(layer) ? layer : "topic";
}

function drawForceGraph(svgSel, nodes, links, emptySel, onNodeClick) {
  const svg = d3.select(svgSel);
  svg.selectAll("*").remove();
  const empty = $(emptySel);
  if (!nodes.length) { if (empty) empty.style.display = "block"; return; }
  if (empty) empty.style.display = "none";

  const rect = svg.node().getBoundingClientRect();
  const width = rect.width || 800;
  const height = rect.height || 420;
  const markerId = `arrow-${svgSel.replace("#", "")}`;

  svg.append("defs").append("marker")
    .attr("id", markerId).attr("viewBox", "0 -5 10 10").attr("refX", 22).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
    .append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", "#94a3b8");

  const g = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.3, 3]).on("zoom", (event) => g.attr("transform", event.transform)));

  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id((d) => d.id).distance(120))
    .force("charge", d3.forceManyBody().strength(-320))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide(34));

  const link = g.append("g").attr("stroke", "#cbd5e1").attr("stroke-width", 1.5).selectAll("line")
    .data(links).join("line").attr("marker-end", `url(#${markerId})`);

  const linkLabel = g.append("g").selectAll("text").data(links).join("text")
    .attr("class", "edge-label").attr("fill", "#64748b").attr("font-size", 10).text((d) => d.relation || "");

  const node = g.append("g").selectAll("g").data(nodes).join("g").call(
    d3.drag()
      .on("start", (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
  );

  node.append("circle").attr("r", 14).attr("fill", (d) => LAYER_COLOR[d.type] || "#64748b").attr("stroke", "#ffffff").attr("stroke-width", 2)
    .style("cursor", onNodeClick ? "pointer" : "default")
    .on("mousemove", (event, d) => showTip(`<strong>${esc(d.id)}</strong><br>${esc(d.detail || d.type)}${onNodeClick ? "<br><em>click to drill into columns</em>" : ""}`, event.pageX, event.pageY))
    .on("mouseleave", hideTip)
    .on("click", (event, d) => { if (onNodeClick) onNodeClick(d); });
  node.append("text").attr("class", "node-label").attr("x", 18).attr("y", 4).attr("font-size", 11).attr("fill", "#0f172a").text((d) => d.label || d.id);

  sim.on("tick", () => {
    link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    linkLabel.attr("x", (d) => (d.source.x + d.target.x) / 2).attr("y", (d) => (d.source.y + d.target.y) / 2);
    node.attr("transform", (d) => `translate(${d.x},${d.y})`);
  });
}

function renderDataLegend() {
  const items = [["topic", "Source topic"], ["intraday", "Intraday"], ["endofday", "Endofday"], ["analytics", "Analytics"]];
  const el = $("#data-legend");
  if (el) el.innerHTML = items.map(([k, label]) => `<span class="legend-chip"><i style="background:${LAYER_COLOR[k]}"></i>${label}</span>`).join("");
}

function renderGraphs() {
  if (!window.d3) return;
  renderDataLegend();
  const nodeMap = new Map();
  const addNode = (id, kind, label, detail) => { if (!nodeMap.has(id)) nodeMap.set(id, { id, type: nodeType(id, kind), label: label || id, detail }); };
  state.dataLineage.forEach((e) => { addNode(e.source, "topic"); addNode(e.target); });
  const dataLinks = state.dataLineage.map((e) => ({ source: e.source, target: e.target, relation: e.relation }));
  drawForceGraph("#data-graph", Array.from(nodeMap.values()), dataLinks, "#data-graph-empty", showColumnLineage);

  const pMap = new Map();
  const pLinks = [];
  state.processLineage.forEach((s) => {
    const markerNode = `marker:${s.marker_id}`;
    const runNode = `run:${s.run_id}`;
    const stepNode = `step:${s.run_id}:${s.step_name}`;
    if (!pMap.has(markerNode)) pMap.set(markerNode, { id: markerNode, type: "marker", label: s.marker_id, detail: "marker" });
    if (!pMap.has(runNode)) { pMap.set(runNode, { id: runNode, type: "run", label: s.run_id, detail: "ingestion run" }); pLinks.push({ source: markerNode, target: runNode, relation: "started" }); }
    pMap.set(stepNode, { id: stepNode, type: "step", label: s.step_name, detail: s.detail });
    pLinks.push({ source: runNode, target: stepNode, relation: s.step_name });
  });
  drawForceGraph("#process-graph", Array.from(pMap.values()), pLinks, "#process-graph-empty");
}

async function showColumnLineage(node) {
  const el = $("#column-lineage");
  if (!el) return;
  const table = node.id;
  let edges = [];
  try { edges = await api(`/api/lineage/columns?table=${encodeURIComponent(table)}`); }
  catch (_) { edges = []; }
  if (!edges.length) {
    el.hidden = false;
    el.innerHTML = `<div class="section-head"><div><p class="eyebrow">Column lineage</p><h3>${esc(table)}</h3></div>
      <button type="button" class="button-link" id="col-close">Close</button></div>
      <p class="hint">No column-level lineage captured for this node (scan a repo with SQL/reports to populate it).</p>`;
    $("#col-close").addEventListener("click", () => { el.hidden = true; });
    return;
  }
  // group by target column
  const byTarget = new Map();
  edges.forEach((e) => {
    const key = `${e.target_table}.${e.target_column}`;
    if (!byTarget.has(key)) byTarget.set(key, { transformation: e.transformation, sources: [] });
    if (e.source_table) byTarget.get(key).sources.push(`${e.source_table}.${e.source_column || "*"}`);
  });
  const rowsHtml = Array.from(byTarget.entries()).map(([target, info]) =>
    `<tr><td>${esc(target)}</td>
      <td>${info.sources.length ? info.sources.map((s) => `<code>${esc(s)}</code>`).join(", ") : "<em>—</em>"}</td>
      <td>${info.transformation ? `<code>${esc(info.transformation)}</code>` : "<em>—</em>"}</td></tr>`).join("");
  el.hidden = false;
  el.innerHTML = `<div class="section-head"><div><p class="eyebrow">Column lineage</p><h3>${esc(table)}</h3></div>
      <button type="button" class="button-link" id="col-close">Close</button></div>
    <table class="col-lineage-table"><thead><tr><th>Column</th><th>Sources</th><th>Transformation</th></tr></thead>
    <tbody>${rowsHtml}</tbody></table>`;
  $("#col-close").addEventListener("click", () => { el.hidden = true; });
}

/* ----------------------------------------------------------------- repo scanner */

function csv(value) { return String(value || "").split(",").map((s) => s.trim()).filter(Boolean); }

async function renderScan() {
  const modeEl = $("#scan-mode");
  if (state.staticMode) { if (modeEl) modeEl.textContent = "Scanning requires the FastAPI backend — not available in the static (GitHub Pages) demo."; }
  const list = $("#scan-sources");
  if (!list) return;
  let sources = [];
  try { sources = await api("/api/scan/sources"); }
  catch (_) { list.innerHTML = `<p class="hint">Connect the backend to configure and run scans.</p>`; return; }
  list.innerHTML = sources.length ? sources.map((s) =>
    `<article class="card"><h4>${esc(s.name)}</h4>
      <div class="meta">${esc(s.path)} · ${esc((s.sql_globs || []).join(", ") || "default SQL globs")}</div>
      <button type="button" class="button-link" data-rescan="${esc(s.id)}">Run scan</button></article>`).join("")
    : `<p class="hint">No sources yet — configure one on the left.</p>`;
  list.querySelectorAll("[data-rescan]").forEach((b) =>
    b.addEventListener("click", () => runScan(b.dataset.rescan)));
}

async function runScan(sourceId) {
  const status = $("#scan-status");
  const result = $("#scan-result");
  try {
    const summary = await api(`/api/scan/sources/${sourceId}/run`, { method: "POST" });
    if (status) { status.hidden = false; status.textContent = `Scanned ${summary.files} file(s) — ${summary.tables} tables, ${summary.columns} column links.`; }
    if (result) result.innerHTML = (summary.warnings || []).length
      ? `<div class="meta">Warnings:</div><ul class="agent-uses">${summary.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`
      : `<div class="meta">No warnings. Open the Lineage Graph and click a node to drill into columns.</div>`;
    await refresh();
    if ($("#graph").classList.contains("active")) renderGraphs();
  } catch (err) {
    if (status) { status.hidden = false; status.textContent = err.message || "Scan failed (backend required)."; }
  }
}

function wireScanForm() {
  const form = $("#scan-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const payload = {
      name: f.name.value.trim(),
      path: f.path.value.trim(),
      sql_globs: csv(f.sql_globs.value),
      report_globs: csv(f.report_globs.value),
      naming_conventions: f.naming_pattern.value.trim() ? [{ pattern: f.naming_pattern.value.trim() }] : [],
      dialect: f.dialect.value.trim(),
    };
    try {
      const src = await api("/api/scan/sources", { method: "POST", body: JSON.stringify(payload) });
      f.reset();
      await renderScan();
      await runScan(src.id);
    } catch (err) {
      const status = $("#scan-status");
      if (status) { status.hidden = false; status.textContent = err.message || "Scanning requires the backend."; }
    }
  });

  const demo = $("#scan-demo");
  if (demo) demo.addEventListener("click", async () => {
    const status = $("#scan-status");
    try {
      const summary = await api("/api/scan/demo", { method: "POST" });
      if (status) { status.hidden = false; status.textContent = `Scanned the sample repo — ${summary.files} files, ${summary.tables} tables, ${summary.columns} column links. Open the Lineage Graph.`; }
      await renderScan();
      await refresh();
      if ($("#graph").classList.contains("active")) renderGraphs();
    } catch (err) {
      if (status) { status.hidden = false; status.textContent = err.message || "Scanning requires the FastAPI backend."; }
    }
  });
}

/* ------------------------------------------------------------------ monitoring */

let monitorTimer = null;

async function renderMonitoring() {
  const list = $("#monitor-list");
  const overall = $("#monitor-overall");
  try {
    const started = performance.now();
    const health = await fetch("/api/health").then((r) => { if (!r.ok) throw new Error("health"); return r.json(); });
    const readiness = await fetch("/api/readiness").then((r) => { if (!r.ok) throw new Error("readiness"); return r.json(); });
    const latency = Math.round(performance.now() - started);
    overall.className = `monitor-overall ${readiness.status === "ready" ? "is-ready" : "is-degraded"}`;
    overall.innerHTML = `<span class="status-dot"></span> Backend ${esc(readiness.status)} · liveness ${esc(health.status)} · ${latency}ms`;
    list.innerHTML = (readiness.checks || []).map((c) =>
      `<article class="card status-card ${c.status === "ok" ? "is-ok" : "is-fail"}">
        <h3><span class="status-dot"></span>${esc(c.name)}</h3>
        <p>${esc(c.detail)}</p>
        <div class="meta">${esc(c.status)} · ${esc(c.latency_ms)}ms</div>
      </article>`).join("");
  } catch (_) {
    overall.className = "monitor-overall is-static";
    overall.innerHTML = `<span class="status-dot"></span> Browser demo mode — backend not connected`;
    const lsOk = (() => { try { localStorage.setItem("_t", "1"); localStorage.removeItem("_t"); return true; } catch { return false; } })();
    const checks = [
      { name: "mode", status: "ok", detail: "static (GitHub Pages) — no FastAPI backend" },
      { name: "localStorage", status: lsOk ? "ok" : "fail", detail: lsOk ? "available — definitions persist across reloads" : "unavailable" },
      { name: "data_loaded", status: state.contracts.length ? "ok" : "fail", detail: `${state.domains.length} domains, ${state.contracts.length} contracts, ${state.catalogs.length} catalogs` }
    ];
    list.innerHTML = checks.map((c) =>
      `<article class="card status-card ${c.status === "ok" ? "is-ok" : "is-fail"}"><h3><span class="status-dot"></span>${esc(c.name)}</h3><p>${esc(c.detail)}</p><div class="meta">${esc(c.status)}</div></article>`).join("");
  }
}

function startMonitoring() {
  renderMonitoring();
  stopMonitoring();
  if ($("#monitor-auto").checked) monitorTimer = setInterval(renderMonitoring, 5000);
}
function stopMonitoring() { if (monitorTimer) { clearInterval(monitorTimer); monitorTimer = null; } }

/* --------------------------------------------------------------------- agents */

let agentsLoaded = false;
async function renderAgents() {
  if (agentsLoaded) return;
  const list = $("#agents-list");
  let agents = [];
  try { agents = await fetch("/agents/index.json").then((r) => r.json()); } catch (_) { agents = []; }
  if (!agents.length) { list.innerHTML = card("No agents found", "The agents registry could not be loaded."); agentsLoaded = true; return; }
  list.innerHTML = agents.map((a) => {
    const install = `# Claude Code\ncurl -o .claude/agents/${a.id}.md \\\n  https://public.suranku.com/agents/${a.file}`;
    return `<article class="card agent-card">
      <h3>${esc(a.name)}</h3>
      <p>${esc(a.summary)}</p>
      <div class="agent-providers">${(a.providers || []).map((p) => `<span class="badge">${esc(p)}</span>`).join("")}</div>
      <ul class="agent-uses">${(a.use_cases || []).map((u) => `<li>${esc(u)}</li>`).join("")}</ul>
      ${a.example ? `<p class="agent-example"><strong>Example:</strong> ${esc(a.example)}</p>` : ""}
      <pre class="agent-install">${esc(install)}</pre>
      <div class="card-actions">
        <a class="button-link primary" href="/agents/${esc(a.file)}" target="_blank" rel="noopener">View / download</a>
        <button type="button" class="button-link copy-install" data-install="${esc(install)}">Copy install</button>
      </div>
    </article>`;
  }).join("");
  list.querySelectorAll(".copy-install").forEach((btn) => btn.addEventListener("click", () => {
    navigator.clipboard?.writeText(btn.dataset.install);
    btn.textContent = "Copied!"; setTimeout(() => { btn.textContent = "Copy install"; }, 1500);
  }));
  agentsLoaded = true;
}

/* ----------------------------------------------------------------------- tabs */

function onTabShown(tab) {
  if (tab === "graph") renderGraphs();
  else if (tab === "monitoring") startMonitoring(); else stopMonitoring();
  if (tab === "agents") renderAgents();
  if (tab === "scan") renderScan();
}

function activateTab(id) {
  const button = document.querySelector(`.tabs button[data-tab="${id}"]`);
  const panel = document.getElementById(id);
  if (!button || !panel) return false;
  document.querySelectorAll(".tabs button").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  button.classList.add("active");
  panel.classList.add("active");
  onTabShown(id);
  return true;
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

// Deep-link a tab via the URL hash, e.g. /data-intelligence-portal/#runs
function activateTabFromHash() {
  const id = (location.hash || "").replace(/^#/, "");
  if (id) activateTab(id);
}
window.addEventListener("hashchange", activateTabFromHash);

/* ---------------------------------------------------------------- top actions */

$("#reset-demo").addEventListener("click", async () => { await api("/api/demo/reset", { method: "POST" }); await refresh(); });
$("#run-demo").addEventListener("click", async () => {
  try { await api("/api/ingestion-runs/demo", { method: "POST" }); } catch (_) { /* demo seed path */ }
  await refresh();
  if ($("#graph").classList.contains("active")) renderGraphs();
});

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value;
  let result;
  try { result = await api("/api/chat", { method: "POST", body: JSON.stringify({ question }) }); }
  catch (_) { result = staticChat(question); }
  $("#chat-answer").innerHTML = `<strong>${esc(result.mode)}</strong><p>${esc(result.answer)}</p><div class="meta">Sources: ${esc((result.sources || []).join(", "))}</div>`;
});

$("#monitor-refresh").addEventListener("click", renderMonitoring);
$("#monitor-auto").addEventListener("change", startMonitoring);

/* ------------------------------------------------------------------------ init */

tooltipEl = $("#graph-tooltip");
wireBuildForms();
wireScanForm();
refresh().then(activateTabFromHash).catch((error) => {
  document.body.insertAdjacentHTML("afterbegin", `<div class="answer">Failed to load portal data: ${esc(error.message)}</div>`);
});
