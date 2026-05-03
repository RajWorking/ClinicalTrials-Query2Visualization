const $ = (id) => document.getElementById(id);

document.querySelectorAll(".examples button").forEach((btn) => {
  btn.addEventListener("click", () => {
    $("query").value = btn.dataset.q || "";
    $("condition").value = btn.dataset.cond || "";
    $("status").value = btn.dataset.status || "";
    $("drug_name").value = btn.dataset.drug || "";
  });
});

$("run").addEventListener("click", run);

async function run() {
  const btn = $("run");
  btn.disabled = true;
  $("status-area").innerHTML = "";
  const body = {
    query: $("query").value,
    drug_name: $("drug_name").value || null,
    condition: $("condition").value || null,
    sponsor: $("sponsor").value || null,
    country: $("country").value || null,
    phase: $("phase").value || null,
    status: $("status").value || null,
    start_year: $("start_year").value ? Number($("start_year").value) : null,
    end_year: $("end_year").value ? Number($("end_year").value) : null,
    max_studies: Number($("max_studies").value) || 500,
  };
  Object.keys(body).forEach((k) => body[k] == null && delete body[k]);

  try {
    const r = await fetch("/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status}: ${txt}`);
    }
    const data = await r.json();
    render(data);
  } catch (e) {
    $("status-area").innerHTML = `<section class="error">${e.message}</section>`;
  } finally {
    btn.disabled = false;
  }
}

function render(resp) {
  $("results").classList.remove("hidden");
  $("title").textContent = resp.visualization.title;
  $("interpretation").textContent =
    resp.meta.query_interpretation +
    `  ·  ${resp.meta.studies_used}/${resp.meta.total_studies_matched} trials used` +
    (resp.meta.truncated ? " (truncated)" : "");
  $("raw-json").textContent = JSON.stringify(resp, null, 2);

  $("viz").innerHTML = "";
  const v = resp.visualization;
  if (v.type === "network_graph") {
    renderNetwork(v);
  } else {
    renderVega(v);
  }
}

function renderNetwork(v) {
  const container = document.createElement("div");
  container.id = "network";
  $("viz").appendChild(container);
  const colorByType = {
    sponsor: "#2563eb",
    drug: "#10b981",
    condition: "#f59e0b",
  };
  const nodes = new vis.DataSet(
    v.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      color: colorByType[n.type] || "#999",
      shape: "dot",
      size: 12,
    })),
  );
  const edges = new vis.DataSet(
    v.edges.map((e) => ({
      from: e.source,
      to: e.target,
      value: e.weight,
      title: edgeTooltip(e),
    })),
  );
  new vis.Network(
    container,
    { nodes, edges },
    {
      physics: { stabilization: { iterations: 200 } },
      edges: { scaling: { min: 1, max: 8 } },
      nodes: { font: { size: 12 } },
    },
  );
}

function edgeTooltip(e) {
  const cites = (e.citations || [])
    .map(
      (c) =>
        `<a href="https://clinicaltrials.gov/study/${c.nct_id}" target="_blank">${c.nct_id}</a>: ${escapeHtml(c.excerpt)}`,
    )
    .join("<br/>");
  return `<div class="tooltip-citations"><strong>${e.source} ↔ ${e.target} (n=${e.weight})</strong>${cites}</div>`;
}

function renderVega(v) {
  const enc = v.encoding || {};
  let mark;
  if (v.type === "time_series") mark = { type: "line", point: true };
  else if (v.type === "scatter_plot") mark = "circle";
  else mark = "bar";

  const vegaEnc = {};
  if (enc.x)
    vegaEnc.x = { field: enc.x.field, type: enc.x.type || "nominal", sort: null };
  if (enc.y) vegaEnc.y = { field: enc.y.field, type: enc.y.type || "quantitative" };
  if (enc.series) {
    vegaEnc.color = { field: enc.series.field, type: "nominal" };
    if (v.type !== "time_series") {
      vegaEnc.xOffset = { field: enc.series.field };
    }
  }
  vegaEnc.tooltip = buildTooltipChannels(v);

  const spec = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: v.title,
    data: { values: flattenForTooltip(v.data) },
    mark,
    encoding: vegaEnc,
    width: "container",
    height: 400,
  };
  vegaEmbed("#viz", spec, { actions: false });
}

function buildTooltipChannels(v) {
  const enc = v.encoding || {};
  const t = [];
  if (enc.x) t.push({ field: enc.x.field, type: enc.x.type || "nominal" });
  if (enc.y) t.push({ field: enc.y.field, type: enc.y.type || "quantitative" });
  if (enc.series) t.push({ field: enc.series.field, type: "nominal" });
  t.push({ field: "citation_summary", type: "nominal", title: "Citations" });
  return t;
}

function flattenForTooltip(data) {
  return (data || []).map((d) => ({
    ...d,
    citation_summary: (d.citations || [])
      .map((c) => `${c.nct_id}: ${c.excerpt.slice(0, 80)}…`)
      .join(" | "),
  }));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[c]);
}
