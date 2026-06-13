const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker");
const statusNode = document.querySelector("#status");
const resultsNode = document.querySelector("#results");
const submitButton = form.querySelector("button[type='submit']");
const screen = document.querySelector(".screen");

input.addEventListener("input", () => {
  input.classList.toggle("has-value", Boolean(input.value.trim()));
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) {
    showError("Enter a ticker first.");
    return;
  }

  resultsNode.hidden = true;
  resultsNode.innerHTML = "";
  setLoading(true, ticker);

  try {
    const response = await fetch(`/api/evaluate?ticker=${encodeURIComponent(ticker)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Evaluation failed");
    }
    renderResults(payload);
    setLoading(false);
  } catch (error) {
    setLoading(false);
    showError(error.message);
  }
});

function setLoading(isLoading, ticker = "") {
  screen.classList.toggle("is-loading", isLoading);
  form.setAttribute("aria-busy", String(isLoading));
  submitButton.disabled = isLoading;
  submitButton.textContent = isLoading ? "Analyzing" : "Evaluate";
  if (!isLoading) {
    statusNode.innerHTML = "";
    return;
  }
  statusNode.innerHTML = `
    <div class="loader-panel" role="status">
      <div class="loader-orbit" aria-hidden="true"></div>
      <div class="loader-copy">
        <strong>Evaluating ${escapeHtml(ticker)}</strong>
        <span>Gathering fundamentals and scoring the checklist</span>
      </div>
    </div>
  `;
}

function showError(message) {
  screen.classList.remove("is-loading");
  statusNode.innerHTML = `<div class="error-message">${escapeHtml(message)}</div>`;
}

function renderResults(data) {
  const metrics = data.metrics || {};
  const rules = data.rules || [];

  resultsNode.innerHTML = `
    <section class="summary">
      <div>
        <h2>${escapeHtml(data.company_name || data.ticker)}</h2>
        <p>${escapeHtml(data.rating)} · ${escapeHtml(metrics.sector || "Sector unknown")} · ${escapeHtml(metrics.industry || "Industry unknown")}</p>
      </div>
      <div class="score">
        <strong>${data.score}/${data.max_score}</strong>
        <span>Score</span>
      </div>
    </section>

    <section class="meta-grid">
      ${metric("Market Cap", formatValue(metrics.market_cap))}
      ${metric("P/E", firstValue(metrics.trailing_pe, metrics.forward_pe))}
      ${metric("Profit Margin", formatPercent(metrics.profit_margin))}
      ${metric("Debt / Equity", normalizeDebtEquity(metrics.debt_to_equity))}
    </section>

    <section class="rule-grid">
      ${rules.map(renderRule).join("")}
    </section>

    ${(data.source_notes || []).map((note) => `<div class="note">${escapeHtml(note)}</div>`).join("")}
  `;
  resultsNode.hidden = false;
  screen.classList.add("has-results");
}

function metric(label, value) {
  return `
    <div class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "Unknown")}</strong>
    </div>
  `;
}

function renderRule(rule) {
  return `
    <article class="rule">
      <div class="rule-head">
        <h3>${escapeHtml(rule.name)}</h3>
        <span class="pill ${escapeHtml(rule.status)}">${escapeHtml(rule.status)}</span>
      </div>
      <p>${escapeHtml(rule.summary)}</p>
      ${rule.target ? `<p><strong>Target:</strong> ${escapeHtml(rule.target)}</p>` : ""}
      ${rule.value !== null && rule.value !== undefined ? `<div class="rule-data">${escapeHtml(JSON.stringify(rule.value))}</div>` : ""}
    </article>
  `;
}

function firstValue(...values) {
  const value = values.find((item) => item !== null && item !== undefined);
  if (value === undefined) return "Unknown";
  return Number(value).toFixed(2);
}

function formatPercent(value) {
  if (value === null || value === undefined) return "Unknown";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function normalizeDebtEquity(value) {
  if (value === null || value === undefined) return "Unknown";
  const number = Number(value);
  return (number > 10 ? number / 100 : number).toFixed(2);
}

function formatValue(value) {
  if (value === null || value === undefined) return "Unknown";
  const number = Number(value);
  if (number >= 1_000_000_000) return `$${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `$${(number / 1_000).toFixed(2)}K`;
  return `$${number.toFixed(2)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
