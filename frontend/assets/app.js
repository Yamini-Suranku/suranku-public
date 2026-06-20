const state = {
  domains: [],
  contracts: [],
  runs: [],
  catalogs: [],
  dataLineage: [],
  processLineage: [],
  staticMode: false
};

const $ = (selector) => document.querySelector(selector);

// Escape untrusted values before injecting into innerHTML. Demo data is safe,
// but a cloned template plugs in real metadata and live AI output.
function esc(value) {
  return String(value === undefined || value === null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const demoSeed = {
  domains: [
    {
      id: "commerce",
      name: "Retail Commerce",
      owner: "Commerce Data Office",
      description: "Retail orders, payments, and shipment events used for the demo data platform."
    }
  ],
  contracts: [
    {
      id: "commerce.orders.created.v1",
      domain_id: "commerce",
      topic: "commerce.orders.created",
      event_name: "orders_created",
      version: "v1",
      primary_keys: ["order_id"],
      description: "Order creation event published by the retail order service.",
      schema: `syntax = "proto3";\n\nmessage OrderCreated {\n  string event_id = 1;\n  string order_id = 2;\n  string customer_id = 3;\n  double order_total = 4;\n}`
    },
    {
      id: "commerce.payments.captured.v1",
      domain_id: "commerce",
      topic: "commerce.payments.captured",
      event_name: "payments_captured",
      version: "v1",
      primary_keys: ["payment_id"],
      description: "Payment capture event published by the payment service.",
      schema: `syntax = "proto3";\n\nmessage PaymentCaptured {\n  string event_id = 1;\n  string payment_id = 2;\n  string order_id = 3;\n  double amount = 4;\n}`
    },
    {
      id: "commerce.shipments.updated.v1",
      domain_id: "commerce",
      topic: "commerce.shipments.updated",
      event_name: "shipments_updated",
      version: "v1",
      primary_keys: ["shipment_id"],
      description: "Shipment status event published by the fulfillment service.",
      schema: `syntax = "proto3";\n\nmessage ShipmentUpdated {\n  string event_id = 1;\n  string shipment_id = 2;\n  string order_id = 3;\n  string shipment_status = 4;\n}`
    }
  ]
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function staticReset() {
  state.domains = clone(demoSeed.domains);
  state.contracts = clone(demoSeed.contracts);
  state.runs = [];
  state.catalogs = [];
  state.dataLineage = [];
  state.processLineage = [];
}

function staticRunIngestion() {
  if (!state.domains.length) staticReset();
  state.runs = state.contracts.map((contract, index) => {
    const runId = `static_run_${index + 1}`;
    const recordsRead = contract.id.includes("orders") ? 3 : 2;
    const recordsDeduped = contract.id.includes("orders") ? 1 : 0;
    return {
      id: runId,
      marker_id: "commerce-batch-001",
      contract_id: contract.id,
      status: "completed",
      records_read: recordsRead,
      records_written: recordsRead - recordsDeduped,
      records_deduped: recordsDeduped,
      output_path: `data/object-store/analytics/commerce/commerce_${contract.event_name}/${runId}.parquet.jsonl`
    };
  });
  state.catalogs = state.contracts.flatMap((contract) =>
    ["intraday", "endofday", "analytics"].map((layer) => ({
      id: `${layer}.${contract.domain_id}.${contract.event_name}`,
      layer,
      domain_id: contract.domain_id,
      table_name: contract.event_name,
      source_contract_id: contract.id,
      storage_path: `data/object-store/${layer}/${contract.domain_id}/commerce_${contract.event_name}/static.parquet.jsonl`,
      record_count: contract.id.includes("orders") ? 2 : 2,
      updated_at: new Date().toISOString()
    }))
  );
  state.dataLineage = state.contracts.flatMap((contract, index) =>
    ["intraday", "endofday", "analytics"].map((layer) => ({
      id: `static_lin_${layer}_${contract.event_name}`,
      source: contract.topic,
      target: `${layer}.${contract.domain_id}.${contract.event_name}`,
      relation: "ingested_to",
      contract_id: contract.id,
      run_id: `static_run_${index + 1}`
    }))
  );
  state.processLineage = state.runs.flatMap((run) => [
    {
      id: `${run.id}_marker`,
      marker_id: run.marker_id,
      run_id: run.id,
      step_name: "marker_discovered",
      detail: `Marker ${run.marker_id} announced ${run.contract_id}`
    },
    {
      id: `${run.id}_dedup`,
      marker_id: run.marker_id,
      run_id: run.id,
      step_name: "records_deduplicated",
      detail: `${run.records_deduped} duplicate records removed by contract primary keys`
    },
    {
      id: `${run.id}_catalogs`,
      marker_id: run.marker_id,
      run_id: run.id,
      step_name: "catalogs_written",
      detail: "intraday, endofday, and analytics layers updated"
    }
  ]);
}

function staticChat(question) {
  const q = question.toLowerCase();
  let answer = "This GitHub Pages demo runs fully in the browser. The Docker/FastAPI version adds persistent SQLite metadata and API endpoints.";
  if (q.includes("lineage")) {
    answer = "Data lineage connects commerce Kafka topics to intraday, endofday, and analytics catalog tables. Process lineage records marker discovery, deduplication, and catalog writes.";
  } else if (q.includes("dedup") || q.includes("primary")) {
    answer = "Deduplication uses primary keys from each contract: order_id for orders, payment_id for payments, and shipment_id for shipments.";
  } else if (q.includes("catalog") || q.includes("iceberg")) {
    answer = "The template models intraday, endofday, and analytics catalogs. The Pages demo simulates them; the local app stores run metadata through FastAPI and SQLite.";
  }
  return { mode: "github-pages-demo", answer, sources: ["browser demo seed", "agent context"] };
}

async function api(path, options = {}) {
  if (state.staticMode) return staticApi(path, options);
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function staticApi(path, options = {}) {
  if (path === "/api/demo/reset") {
    staticReset();
    return { status: "reset", domains: state.domains.length, contracts: state.contracts.length };
  }
  if (path === "/api/ingestion-runs/demo") {
    staticRunIngestion();
    return { marker_id: "commerce-batch-001", runs: state.runs };
  }
  if (path === "/api/domains") return state.domains;
  if (path === "/api/contracts") return state.contracts;
  if (path === "/api/ingestion-runs") return state.runs;
  if (path === "/api/catalogs") return state.catalogs;
  if (path === "/api/lineage/data") return state.dataLineage;
  if (path === "/api/lineage/process") return state.processLineage;
  if (path === "/api/chat") {
    const body = options.body ? JSON.parse(options.body) : { question: "" };
    return staticChat(body.question || "");
  }
  throw new Error(`Unsupported static endpoint: ${path}`);
}

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
  $("#domains-list").innerHTML = state.domains.map((d) =>
    card(d.name, d.description, `Owner: ${d.owner}`)
  ).join("");
}

function renderContracts() {
  $("#contracts-list").innerHTML = state.contracts.map((c) =>
    `<article class="card">
      <h3>${esc(c.topic)}</h3>
      <p>${esc(c.description)}</p>
      <div class="meta">Event: ${esc(c.event_name)} | Version: ${esc(c.version)} | Primary keys: ${esc((c.primary_keys || []).join(", "))}</div>
      <pre>${esc(c.schema)}</pre>
    </article>`
  ).join("");
}

function renderRuns() {
  $("#runs-list").innerHTML = state.runs.length ? state.runs.map((run) =>
    card(
      run.id,
      `${run.status}: ${run.records_written} written, ${run.records_deduped} deduped, ${run.records_read} read.`,
      `Marker: ${run.marker_id} | Output: ${run.output_path}`
    )
  ).join("") : card("No ingestion runs yet", "Use Run ingestion to process the demo marker and events.");
}

function renderCatalogs() {
  $("#catalogs-list").innerHTML = state.catalogs.length ? state.catalogs.map((table) =>
    card(
      `${table.layer}.${table.domain_id}.${table.table_name}`,
      `${table.record_count} records stored at ${table.storage_path}`,
      `Source contract: ${table.source_contract_id}`
    )
  ).join("") : card("No catalog tables yet", "Run ingestion to create intraday, endofday, and analytics catalog entries.");
}

function renderLineage() {
  $("#data-lineage-list").innerHTML = state.dataLineage.length ? state.dataLineage.map((edge) =>
    card(edge.relation, `${edge.source} -> ${edge.target}`, `Run: ${edge.run_id}`)
  ).join("") : card("No data lineage yet", "Run ingestion to create topic-to-table lineage.");

  $("#process-lineage-list").innerHTML = state.processLineage.length ? state.processLineage.map((step) =>
    card(step.step_name, step.detail, `Marker: ${step.marker_id} | Run: ${step.run_id}`)
  ).join("") : card("No process lineage yet", "Run ingestion to create marker and processing evidence.");
}

function renderAll() {
  renderMetrics();
  renderDomains();
  renderContracts();
  renderRuns();
  renderCatalogs();
  renderLineage();
}

async function refresh() {
  try {
    [state.domains, state.contracts, state.runs, state.catalogs, state.dataLineage, state.processLineage] = await Promise.all([
      api("/api/domains"),
      api("/api/contracts"),
      api("/api/ingestion-runs"),
      api("/api/catalogs"),
      api("/api/lineage/data"),
      api("/api/lineage/process")
    ]);
  } catch (error) {
    state.staticMode = true;
    staticReset();
  }
  renderAll();
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(button.dataset.tab).classList.add("active");
  });
});

$("#reset-demo").addEventListener("click", async () => {
  await api("/api/demo/reset", { method: "POST" });
  await refresh();
});

$("#run-demo").addEventListener("click", async () => {
  await api("/api/ingestion-runs/demo", { method: "POST" });
  await refresh();
});

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value;
  const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ question }) });
  $("#chat-answer").innerHTML = `<strong>${esc(result.mode)}</strong><p>${esc(result.answer)}</p><div class="meta">Sources: ${esc((result.sources || []).join(", "))}</div>`;
});

refresh().catch((error) => {
  document.body.insertAdjacentHTML("afterbegin", `<div class="answer">Failed to load portal data: ${esc(error.message)}</div>`);
});
