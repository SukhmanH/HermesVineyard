"use strict";

const $ = (id) => document.getElementById(id);
const state = { data: null, section: "blocks", page: 0, sort: null, direction: 1, loading: false };
const pageSize = 15;
const groups = [
  ["WORKSPACE", [["overview", "Overview"], ["blocks", "Vineyard blocks"], ["weather", "Weather"], ["restrictions", "Safety & re-entry"]]],
  ["OPERATIONS", [["sprays", "Spray records"], ["tasks", "Field tasks"], ["crew", "Crew & hours"], ["maturity", "Fruit & harvest"], ["irrigation", "Irrigation"]]],
  ["MANAGEMENT", [["products", "Product registry"], ["drafts", "Pending confirmations"], ["listings", "Property watch"], ["activity", "Hermes activity"], ["packing", "Packing records"]]],
];
const numberFormat = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 2 });
const taskNames = { poda: "Pruning", deshoje: "Leaf removal", desbrote: "Shoot thinning", riego: "Irrigation", corte_pasto: "Mowing", alambre: "Wire work", cosecha: "Harvest", otro: "Other" };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function format(value, key = "") {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "number") {
    if (key === "price") return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 }).format(value);
    return numberFormat.format(value);
  }
  if (key === "task_type") return taskNames[value] || value;
  return String(value);
}

function empty(title, description) {
  const node = element("div", "empty");
  node.append(element("h3", "", title), element("p", "", description));
  return node;
}

function getSection(id) {
  return state.data?.sections.find((section) => section.id === id);
}

function renderNavigation() {
  const nav = $("navigation");
  for (const [title, entries] of groups) {
    nav.append(element("p", "nav-group", title));
    for (const [id, label] of entries) {
      const link = element("a", "", "");
      link.href = `#${id}`;
      link.dataset.section = id;
      const mark = element("span", "nav-mark", id === "overview" ? "◫" : "·");
      mark.setAttribute("aria-hidden", "true");
      link.append(mark, document.createTextNode(label));
      nav.append(link);
    }
  }
}

function renderMetrics() {
  $("metrics").replaceChildren(...state.data.metrics.map((metric) => {
    const node = element("article", `metric ${metric.tone || "neutral"}`);
    node.append(element("p", "metric-label", metric.label), element("p", "metric-value", metric.value == null ? "—" : format(metric.value)), element("p", "metric-detail", metric.detail));
    return node;
  }));
  $("metrics").setAttribute("aria-busy", "false");
}

function renderAlerts() {
  const alerts = state.data.alerts.map((alert) => {
    const node = element("article", `alert ${alert.tone}`);
    const mark = element("span", "alert-mark", alert.tone === "neutral" ? "i" : "!");
    mark.setAttribute("aria-hidden", "true");
    const content = element("div");
    content.append(element("h3", "", alert.title), element("p", "", alert.detail));
    node.append(mark, content);
    return node;
  });
  $("alerts").replaceChildren(...(alerts.length ? alerts : [empty("No record alerts", "No alerts in this snapshot. This is not a safety clearance.")]));
}

function panel(title, sectionId) {
  const node = element("article", "panel");
  const head = element("div", "panel-head");
  const link = element("a", "", "View records →");
  link.href = `#${sectionId}`;
  head.append(element("h3", "", title), link);
  node.append(head);
  return node;
}

function renderOverview() {
  const weather = panel("A watch on every site", "weather");
  const weatherData = getSection("weather");
  if (!weatherData || weatherData.error) {
    weather.append(empty("Weather status unknown", "The saved weather could not be read. No absence or safety status can be inferred."));
  } else if (weatherData.rows.length) {
    for (const row of weatherData.rows) {
      const node = element("div", "site-row");
      const name = element("div");
      name.append(element("strong", "", row.site), element("small", "", `${format(row.source)} · ${format(row.fetched_at_utc)}`));
      node.append(name, element("span", `pill ${row.status === "fresh" ? "fresh" : ""}`, `${row.status} cache`));
      weather.append(node);
    }
    weather.append(element("p", "subtle", "Cache freshness only. No spray approval is given here."));
  } else weather.append(empty("Weather unavailable", "Hermes has not saved weather for this view."));
  const vineyard = panel("Your land, by site", "blocks");
  const blocks = getSection("blocks");
  const sites = new Map();
  for (const row of blocks?.rows || []) {
    const site = sites.get(row.site) || { count: 0, acres: 0, missing: false };
    site.count += 1;
    if (typeof row.acres === "number") site.acres += row.acres;
    else site.missing = true;
    sites.set(row.site, site);
  }
  for (const [name, site] of sites) {
    const node = element("div", "site-row");
    const content = element("div");
    content.append(element("strong", "", name), element("small", "", `${site.count} registered ${site.count === 1 ? "block" : "blocks"}`));
    node.append(content, element("span", "pill fresh", site.missing ? "Acreage incomplete" : `${format(site.acres)} acres`));
    vineyard.append(node);
  }
  if (!blocks || blocks.error) vineyard.append(empty("Registry unavailable", "The block registry could not be read. Acreage and block counts are unknown."));
  else if (!sites.size) vineyard.append(empty("No blocks recorded", "Your active block registry will appear here."));
  vineyard.append(element("p", "subtle", blocks?.total > blocks?.rows.length ? "Based on the first 200 displayed blocks; see the summary for total acreage." : "Recorded acreage across your active vineyard blocks."));
  $("overview-panels").replaceChildren(weather, vineyard);
}

function selectView() {
  const requested = location.hash.slice(1) || "overview";
  const id = requested === "overview" || getSection(requested) ? requested : "overview";
  const section = getSection(id === "overview" ? state.section : id);
  if (section && state.section !== section.id) {
    state.section = section.id;
    state.page = 0;
    state.sort = null;
    $("search").value = "";
  }
  document.querySelectorAll("nav a").forEach((link) => {
    const selected = link.dataset.section === id;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("overview-panels").hidden = id !== "overview";
  $("page-title").textContent = id === "overview" ? "The grower's overview." : section?.title || "Vineyard records";
  $("breadcrumb").textContent = id === "overview" ? "Overview" : section?.title || "Records";
  $("page-description").textContent = id === "overview" ? "One place for the field, the crew, and the record." : "Your latest saved records. Safety alerts always remain in view.";
  document.title = `Hermes · ${$("breadcrumb").textContent}`;
  if (state.data) renderTable();
}

function filteredRows() {
  const query = $("search").value.toLocaleLowerCase().trim();
  const section = getSection(state.section);
  const rows = (section?.rows || []).filter((row) => Object.entries(row).some(([key, value]) => String(value ?? "").toLocaleLowerCase().includes(query) || format(value, key).toLocaleLowerCase().includes(query)));
  if (state.sort) rows.sort((a, b) => {
    const x = a[state.sort];
    const y = b[state.sort];
    if (x == null) return y == null ? 0 : 1;
    if (y == null) return -1;
    return state.direction * (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true }));
  });
  return rows;
}

function cell(value, key) {
  const node = element("td");
  if (value == null || value === "") node.append(element("span", "missing", "Not recorded"));
  else if (key === "url") {
    try {
      const url = new URL(value);
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) throw new Error("Invalid URL");
      const link = element("a", "", "View listing ↗");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      node.append(link);
    } catch { node.textContent = "Link unavailable"; }
  } else if (key === "status") {
    const tone = value === "fresh" || value === "verified" ? "fresh" : String(value).includes("entry") ? "danger" : "";
    node.append(element("span", `pill ${tone}`, value));
  } else node.textContent = format(value, key);
  return node;
}

function renderTable() {
  const section = getSection(state.section);
  if (!section) return;
  $("records-title").textContent = section.title;
  $("records-description").textContent = section.description;
  $("record-tabs").replaceChildren(...state.data.sections.map((item) => {
    const button = element("button", item.id === state.section ? "active" : "", item.title);
    button.type = "button";
    button.setAttribute("aria-pressed", String(item.id === state.section));
    button.addEventListener("click", () => { location.hash = item.id; });
    return button;
  }));
  const area = $("table-area");
  area.replaceChildren();
  if (section.error) area.append(element("div", "section-error", section.error));
  const rows = filteredRows();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  state.page = Math.min(state.page, pages - 1);
  if (!rows.length) {
    area.append(empty(section.error ? "This record is unavailable" : $("search").value ? "No matching records" : "Nothing recorded yet", section.error ? "Other sections are still available. The database has not been changed." : $("search").value ? "Try a different search. Search covers the loaded rows only." : "Confirmed records will appear here after Hermes saves them."));
  } else {
    const scroll = element("div", "table-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", `${section.title} records; scroll horizontally for more columns`);
    const table = element("table");
    const head = element("thead");
    const heading = element("tr");
    for (const column of section.columns) {
      const th = element("th");
      th.scope = "col";
      th.setAttribute("aria-sort", state.sort === column.key ? state.direction === 1 ? "ascending" : "descending" : "none");
      const button = element("button", "", `${column.label}${state.sort === column.key ? state.direction === 1 ? " ↑" : " ↓" : ""}`);
      button.type = "button";
      button.addEventListener("click", () => {
        state.direction = state.sort === column.key ? -state.direction : 1;
        state.sort = column.key;
        state.page = 0;
        renderTable();
      });
      th.append(button);
      heading.append(th);
    }
    head.append(heading);
    const body = element("tbody");
    for (const row of rows.slice(state.page * pageSize, (state.page + 1) * pageSize)) {
      const tr = element("tr");
      tr.append(...section.columns.map((column) => cell(row[column.key], column.key)));
      body.append(tr);
    }
    table.append(head, body);
    scroll.append(table);
    area.append(scroll);
  }
  $("record-count").textContent = `${rows.length} matching · ${section.rows.length} loaded · ${section.error ? "total may be unavailable" : `${section.total} on record`}`;
  $("page-number").textContent = `${state.page + 1} / ${pages}`;
  $("previous").disabled = state.page === 0;
  $("next").disabled = state.page + 1 >= pages;
  $("download").disabled = rows.length === 0;
}

function exportCsv() {
  const section = getSection(state.section);
  if (!section) return;
  const quote = (value) => {
    let text = value == null ? "" : String(value);
    if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const lines = [section.columns.map((column) => quote(column.label)).join(","), ...filteredRows().map((row) => section.columns.map((column) => quote(row[column.key])).join(","))];
  const url = URL.createObjectURL(new Blob(["\ufeff", lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const link = element("a");
  link.href = url;
  link.download = `hermes-${section.id}-displayed-records.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function refresh() {
  if (state.loading) return;
  state.loading = true;
  $("refresh").disabled = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(response.status === 503 ? "Database unavailable. Check the configured database and retry." : "The local dashboard could not load your records.");
    const data = await response.json();
    if (!Array.isArray(data.sections) || !Array.isArray(data.metrics) || !Array.isArray(data.alerts)) throw new Error("The dashboard received an invalid snapshot.");
    state.data = data;
    const updated = new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "short", timeZone: data.timezone }).format(new Date(data.generated_at));
    $("sync-status").textContent = `Snapshot ${updated}`;
    $("timezone").textContent = data.timezone;
    $("today").textContent = new Intl.DateTimeFormat("en-CA", { weekday: "long", month: "long", day: "numeric", timeZone: data.timezone }).format(new Date(data.generated_at)).toUpperCase();
    $("connection-dot").classList.remove("offline");
    $("error-banner").hidden = true;
    renderMetrics();
    renderAlerts();
    renderOverview();
    selectView();
  } catch (error) {
    $("error-banner").textContent = `${error.name === "AbortError" ? "The local server took too long to respond." : error.message} ${state.data ? "Showing the last successful snapshot; it may be out of date." : "No records have been loaded."}`;
    $("error-banner").hidden = false;
    $("connection-dot").classList.add("offline");
    $("sync-status").textContent = "Connection unavailable · retry with Refresh data";
    if (!state.data) {
      $("metrics").replaceChildren(empty("Records unavailable", "Start the dashboard with an existing vineyard database."));
      $("metrics").setAttribute("aria-busy", "false");
      $("alerts").replaceChildren(empty("Safety status unknown", "Do not assume there are no restrictions when records cannot be read."));
    }
  } finally {
    clearTimeout(timeout);
    state.loading = false;
    $("refresh").disabled = false;
  }
}

renderNavigation();
$("refresh").addEventListener("click", refresh);
$("search").addEventListener("input", () => { state.page = 0; renderTable(); });
$("previous").addEventListener("click", () => { state.page = Math.max(0, state.page - 1); renderTable(); });
$("next").addEventListener("click", () => { state.page += 1; renderTable(); });
$("download").addEventListener("click", exportCsv);
window.addEventListener("hashchange", selectView);
selectView();
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
