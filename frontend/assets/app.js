const state = {
  domains: [],
  contracts: [],
  runs: [],
  catalogs: [],
  dataLineage: [],
  processLineage: []
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function card(title, body, meta = "") {
  return `<article class="card"><h3>${title}</h3><p>${body}</p>${meta ? `<div class="meta">${meta}</div>` : ""}</article>`;
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
      <h3>${c.topic}</h3>
      <p>${c.description}</p>
      <div class="meta">Event: ${c.event_name} | Version: ${c.version} | Primary keys: ${c.primary_keys.join(", ")}</div>
      <pre>${c.schema.replaceAll("<", "&lt;")}</pre>
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
  [state.domains, state.contracts, state.runs, state.catalogs, state.dataLineage, state.processLineage] = await Promise.all([
    api("/api/domains"),
    api("/api/contracts"),
    api("/api/ingestion-runs"),
    api("/api/catalogs"),
    api("/api/lineage/data"),
    api("/api/lineage/process")
  ]);
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
  $("#chat-answer").innerHTML = `<strong>${result.mode}</strong><p>${result.answer}</p><div class="meta">Sources: ${result.sources.join(", ")}</div>`;
});

refresh().catch((error) => {
  document.body.insertAdjacentHTML("afterbegin", `<div class="answer">Failed to load portal data: ${error.message}</div>`);
});
