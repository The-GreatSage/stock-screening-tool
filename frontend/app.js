const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker");
const statusNode = document.querySelector("#status");
const resultsNode = document.querySelector("#results");
const submitButton = form.querySelector("button[type='submit']");
const screen = document.querySelector(".screen");
const backgroundCanvas = document.querySelector("#market-background");
const homeButton = document.querySelector("#home-button");
const resetButton = document.querySelector("#reset-button");
const marketTape = document.querySelector("#market-tape");
let activeRequest = null;
let activeMarketRequest = null;
let activePerformanceRequest = null;
let performanceChartState = null;

startMarketBackground(backgroundCanvas);
loadMarketOverview();
homeButton.addEventListener("click", returnHome);
resetButton.addEventListener("click", returnHome);

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
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;

  try {
    const response = await fetch(`/api/evaluate?ticker=${encodeURIComponent(ticker)}`, {
      signal: request.signal,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Evaluation failed");
    }
    if (activeRequest !== request) return;
    renderResults(payload);
    setLoading(false);
  } catch (error) {
    if (error.name === "AbortError") return;
    setLoading(false);
    showError(error.message);
  } finally {
    if (activeRequest === request) activeRequest = null;
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

function returnHome() {
  activeRequest?.abort();
  activeRequest = null;
  activeMarketRequest?.abort();
  activeMarketRequest = null;
  activePerformanceRequest?.abort();
  activePerformanceRequest = null;
  destroyPerformanceChart();
  setLoading(false);
  screen.classList.remove("has-results");
  resultsNode.hidden = true;
  resultsNode.innerHTML = "";
  statusNode.innerHTML = "";
  input.value = "";
  input.classList.remove("has-value");
  input.focus();
  loadMarketOverview();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderResults(data) {
  const metrics = data.metrics || {};
  const rules = data.rules || [];
  const recentNews = metrics.recent_news || [];
  const earningsReports = metrics.recent_earnings_reports || [];

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

    <section id="performance-chart" class="performance-chart" aria-label="Relative performance chart">
      <div class="performance-head">
        <div>
          <span>Relative performance</span>
          <h2>${escapeHtml(data.ticker)} vs. industry benchmarks</h2>
        </div>
        <div class="performance-periods" aria-label="Chart period">
          ${["1M", "3M", "6M", "1Y"].map((period) => `<button type="button" data-period="${period}" class="${period === "1Y" ? "active" : ""}">${period}</button>`).join("")}
        </div>
      </div>
      <div class="performance-loading">Loading performance history</div>
    </section>

    <section class="rule-grid">
      ${rules.map(renderRule).join("")}
    </section>

    <section class="activity-section" aria-label="Recent company activity">
      <div class="activity-heading">
        <span>Recent activity</span>
        <h2>News and earnings</h2>
      </div>
      <div class="activity-grid">
        ${activityColumn("Most recent news", recentNews, renderNewsItem, "No recent company news was available.")}
        ${activityColumn("Recent earnings reports", earningsReports, renderEarningsItem, "No completed earnings reports were available.")}
      </div>
    </section>

    ${renderSources(data.source_notes || [])}
  `;
  resultsNode.hidden = false;
  screen.classList.add("has-results");
  loadPerformanceChart(data.ticker, metrics.sector || "", metrics.industry || "");
}

async function loadPerformanceChart(ticker, sector, industry) {
  activePerformanceRequest?.abort();
  destroyPerformanceChart();
  const request = new AbortController();
  activePerformanceRequest = request;
  const query = new URLSearchParams({ ticker, sector, industry });
  try {
    const response = await fetch(`/api/performance?${query}`, { signal: request.signal });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Performance history unavailable");
    if (activePerformanceRequest !== request) return;
    renderPerformanceChart(payload);
  } catch (error) {
    if (error.name === "AbortError") return;
    const chart = document.querySelector("#performance-chart");
    if (chart) chart.innerHTML = `<div class="performance-empty">Performance comparison temporarily unavailable.</div>`;
  } finally {
    if (activePerformanceRequest === request) activePerformanceRequest = null;
  }
}

function renderPerformanceChart(payload) {
  const chart = document.querySelector("#performance-chart");
  if (!chart) return;
  const series = payload.series || [];
  if (!series.length) {
    chart.innerHTML = `<div class="performance-empty">Performance history was unavailable for this company and its selected benchmarks.</div>`;
    return;
  }
  chart.innerHTML = `
    <div class="performance-head">
      <div>
        <span>Relative performance</span>
        <h2>${escapeHtml(payload.ticker)} vs. industry benchmarks</h2>
        <p>${escapeHtml(payload.rationale || "Benchmarks selected from company classification")}</p>
      </div>
      <div class="performance-periods" aria-label="Chart period">
        ${["1M", "3M", "6M", "1Y"].map((period) => `<button type="button" data-period="${period}" class="${period === "1Y" ? "active" : ""}">${period}</button>`).join("")}
      </div>
    </div>
    <div class="performance-legend">
      ${series.map((item, index) => `<span><i style="--series-color:${chartColor(index)}"></i>${escapeHtml(item.name)}</span>`).join("")}
    </div>
    <div class="performance-canvas-wrap">
      <canvas aria-label="Normalized stock and benchmark performance chart"></canvas>
      <div class="performance-tooltip" hidden></div>
    </div>
  `;
  const canvas = chart.querySelector("canvas");
  const tooltip = chart.querySelector(".performance-tooltip");
  performanceChartState = { chart, canvas, tooltip, series, period: "1Y", filtered: [] };
  chart.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => {
      chart.querySelectorAll("[data-period]").forEach((item) => item.classList.toggle("active", item === button));
      performanceChartState.period = button.dataset.period;
      drawPerformanceChart();
    });
  });
  canvas.addEventListener("pointermove", showPerformanceTooltip);
  canvas.addEventListener("pointerleave", () => {
    tooltip.hidden = true;
    drawPerformanceChart();
  });
  performanceChartState.observer = new ResizeObserver(drawPerformanceChart);
  performanceChartState.observer.observe(canvas.parentElement);
  drawPerformanceChart();
}

function destroyPerformanceChart() {
  performanceChartState?.observer?.disconnect();
  performanceChartState = null;
}

function drawPerformanceChart(highlightIndex = null) {
  const state = performanceChartState;
  if (!state) return;
  const { canvas, series, period } = state;
  const width = canvas.parentElement.clientWidth;
  const height = canvas.parentElement.clientHeight;
  if (!width || !height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  const filtered = filterPerformanceSeries(series, period);
  state.filtered = filtered;
  const allValues = filtered.flatMap((item) => item.points.map((point) => point.value));
  if (!allValues.length) return;
  let minValue = Math.min(...allValues, 0);
  let maxValue = Math.max(...allValues, 0);
  const spread = Math.max(maxValue - minValue, 10);
  minValue -= spread * 0.12;
  maxValue += spread * 0.12;
  const padding = { top: 16, right: 18, bottom: 28, left: 48 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const maxPoints = Math.max(...filtered.map((item) => item.points.length));
  const xFor = (index) => padding.left + (index / Math.max(maxPoints - 1, 1)) * plotWidth;
  const yFor = (value) => padding.top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;

  context.font = '10px "SF Pro Text", sans-serif';
  context.lineWidth = 1;
  for (let row = 0; row <= 4; row += 1) {
    const value = maxValue - ((maxValue - minValue) / 4) * row;
    const y = yFor(value);
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.strokeStyle = "rgba(255,255,255,0.08)";
    context.stroke();
    context.fillStyle = "#71717a";
    context.textAlign = "right";
    context.fillText(`${value >= 0 ? "+" : ""}${value.toFixed(0)}%`, padding.left - 8, y + 3);
  }

  filtered.forEach((item, seriesIndex) => {
    context.beginPath();
    item.points.forEach((point, index) => {
      const x = xFor(index);
      const y = yFor(point.value);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.strokeStyle = chartColor(seriesIndex);
    context.lineWidth = seriesIndex === 0 ? 2.4 : 1.6;
    context.stroke();
  });

  const primaryPoints = filtered[0]?.points || [];
  if (highlightIndex !== null && primaryPoints[highlightIndex]) {
    const x = xFor(highlightIndex);
    context.beginPath();
    context.moveTo(x, padding.top);
    context.lineTo(x, padding.top + plotHeight);
    context.strokeStyle = "rgba(255,255,255,0.38)";
    context.stroke();
  }

  const firstDate = primaryPoints[0]?.date;
  const lastDate = primaryPoints[primaryPoints.length - 1]?.date;
  context.fillStyle = "#71717a";
  context.textAlign = "left";
  if (firstDate) context.fillText(formatShortDate(firstDate), padding.left, height - 7);
  context.textAlign = "right";
  if (lastDate) context.fillText(formatShortDate(lastDate), width - padding.right, height - 7);
}

function filterPerformanceSeries(series, period) {
  const days = { "1M": 31, "3M": 93, "6M": 186, "1Y": 370 }[period] || 370;
  const latestDate = Math.max(...series.flatMap((item) => item.points.map((point) => new Date(`${point.date}T00:00:00`).getTime())));
  const cutoff = latestDate - days * 86_400_000;
  return series.map((item) => {
    const points = item.points.filter((point) => new Date(`${point.date}T00:00:00`).getTime() >= cutoff);
    if (!points.length) return { ...item, points: [] };
    const baseline = points[0].value;
    return { ...item, points: points.map((point) => ({ ...point, value: point.value - baseline })) };
  });
}

function showPerformanceTooltip(event) {
  const state = performanceChartState;
  if (!state?.filtered.length) return;
  const rect = state.canvas.getBoundingClientRect();
  const primary = state.filtered[0].points;
  const plotStart = 48;
  const plotWidth = rect.width - 66;
  const index = Math.max(0, Math.min(primary.length - 1, Math.round(((event.clientX - rect.left - plotStart) / plotWidth) * (primary.length - 1))));
  const date = primary[index]?.date;
  if (!date) return;
  const rows = state.filtered.map((item, seriesIndex) => {
    if (!item.points.length) return "";
    const point = item.points.reduce((closest, candidate) => Math.abs(new Date(candidate.date) - new Date(date)) < Math.abs(new Date(closest.date) - new Date(date)) ? candidate : closest, item.points[0]);
    return `<span><i style="--series-color:${chartColor(seriesIndex)}"></i>${escapeHtml(item.name)} <strong>${point.value >= 0 ? "+" : ""}${point.value.toFixed(1)}%</strong></span>`;
  }).join("");
  state.tooltip.innerHTML = `<time>${formatDate(date)}</time>${rows}`;
  state.tooltip.hidden = false;
  state.tooltip.style.left = `${Math.min(Math.max(event.clientX - rect.left + 12, 8), rect.width - 184)}px`;
  state.tooltip.style.top = `${Math.max(event.clientY - rect.top - 34, 8)}px`;
  drawPerformanceChart(index);
}

function chartColor(index) {
  return ["#ffffff", "#38bdf8", "#f59e0b"][index] || "#a1a1aa";
}

function formatShortDate(value) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(`${value}T00:00:00`));
}

async function loadMarketOverview() {
  activeMarketRequest?.abort();
  const request = new AbortController();
  activeMarketRequest = request;
  marketTape.hidden = false;
  marketTape.innerHTML = `
    <div class="market-tape-head">
      <span>US Markets</span>
      <span class="market-tape-status">Loading live quotes</span>
    </div>
    <div class="market-tape-loading"></div>
  `;
  try {
    const response = await fetch("/api/markets", { signal: request.signal });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Market quotes unavailable");
    if (activeMarketRequest !== request) return;
    renderMarketTape(payload.markets || []);
  } catch (error) {
    if (error.name === "AbortError") return;
    marketTape.innerHTML = `
      <div class="market-tape-head">
        <span>US Markets</span>
        <span class="market-tape-status">Quotes temporarily unavailable</span>
      </div>
    `;
  } finally {
    if (activeMarketRequest === request) activeMarketRequest = null;
  }
}

function renderMarketTape(markets) {
  if (!markets.length) {
    marketTape.innerHTML = `
      <div class="market-tape-head">
        <span>US Markets</span>
        <span class="market-tape-status">Quotes temporarily unavailable</span>
      </div>
    `;
    return;
  }
  const items = markets.map(renderMarketItem).join("");
  marketTape.innerHTML = `
    <div class="market-tape-head">
      <span>US Markets</span>
      <span class="market-tape-status">Latest quotes</span>
    </div>
    <div class="market-tape-window">
      <div class="market-tape-track">
        <div class="market-tape-group">${items}</div>
        <div class="market-tape-group" aria-hidden="true">${items}</div>
      </div>
    </div>
  `;
}

function renderMarketItem(market) {
  const direction = Number(market.change) >= 0 ? "up" : "down";
  return `
    <article class="market-quote ${direction}">
      <div>
        <strong>${escapeHtml(market.name || market.symbol)}</strong>
        <span>${escapeHtml(market.symbol || "")}</span>
      </div>
      <div class="market-quote-values">
        <strong>${formatMarketPrice(market.price)}</strong>
        <span>${formatMarketChange(market.change, market.change_percent)}</span>
      </div>
    </article>
  `;
}

function metric(label, value) {
  return `
    <div class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "Unknown")}</strong>
    </div>
  `;
}

const ruleTitles = {
  roic: "ROIC",
  buyback_dilution: "Cash Buyback",
  margins: "Profit & Operating Margin",
  earnings_size: "Company Earnings",
  valuation: "P/E, PEG & PEGY",
  market_cap: "Market Cap (Above $200M up to $7B)",
  pe_end_of_run: "Extreme P/E",
  debt_to_equity: "Debt-to-Equity Ratio",
  yoy_revenue_growth: "YoY Revenue Growth (15%-20% YoY Growth)",
  insider_ownership: "Insider Ownership",
  margin_shrinkage: "Revenue Growth and Margin Shrinkage",
  recent_cluster_purchase: "Recent Cluster Purchase",
  constant_revenue_earnings_growth: "Constant Revenue Growth & Earnings",
  strategic_investors: "Strategic Investors",
};

const ruleDescriptions = {
  roic: "Measures after-tax operating profit against average invested capital.",
  buyback_dilution: "Reviews diluted share-count history and reported cash spent on share repurchases.",
  margins: "Compares current profit and operating margins with the preferred quality thresholds.",
  earnings_size: "Uses the latest available quarterly and annual net income.",
  valuation: "Compares earnings valuation with growth and dividend yield where the inputs are available.",
  market_cap: "Uses the latest reported market capitalization to assess company size.",
  pe_end_of_run: "Flags elevated valuation when trailing or forward P/E enters the 40-50 range.",
  debt_to_equity: "Compares total debt with shareholder equity using the latest available balance sheet.",
  yoy_revenue_growth: "Compares the latest annual revenue with the prior fiscal year.",
  insider_ownership: "Measures shares held by insiders as a percentage of shares outstanding.",
  margin_shrinkage: "Checks whether net profit margin is weakening while annual revenue grows.",
  recent_cluster_purchase: "Checks for open-market purchases by multiple distinct insiders within 180 days.",
  constant_revenue_earnings_growth: "Reviews annual revenue and net-income growth across available periods.",
  strategic_investors: "Identifies sizable positions held by major institutions or potentially strategic investors.",
};

const ruleValueLabels = {
  roic: "ROIC",
  nopat: "NOPAT",
  average_invested_capital: "Avg. Invested Capital",
  tax_rate: "Tax Rate",
  share_count_change: "Share Count Change",
  latest_repurchase_cash_flow: "Latest Repurchase",
  profit_margin: "Profit Margin",
  operating_margin: "Operating Margin",
  quarterly: "Quarterly Earnings",
  annual: "Annual Earnings",
  pe: "P/E",
  peg: "PEG",
  pegy: "PEGY",
  latest_yoy_growth: "Latest YoY Growth",
  first_margin: "First Margin",
  latest_margin: "Latest Margin",
  distinct_insiders: "Distinct Insiders",
  purchase_count: "Purchases",
  total_value: "Total Purchase Value",
  qualifying_count: "Qualifying Investors",
  revenue_growth: "Revenue Growth",
  earnings_growth: "Earnings Growth",
};

function renderRule(rule) {
  const title = ruleTitles[rule.id] || rule.name;
  const details = rule.details || ruleDescriptions[rule.id];
  return `
    <article class="rule">
      <div class="rule-head">
        <h3>${escapeHtml(title)}</h3>
        <span class="pill ${escapeHtml(rule.status)}">${escapeHtml(rule.status)}</span>
      </div>
      ${renderRuleOutput(rule)}
      ${rule.target ? `
        <div class="rule-benchmark">
          <span>Benchmark</span>
          <strong>${escapeHtml(rule.target)}</strong>
        </div>
      ` : ""}
      <p class="rule-summary">${escapeHtml(rule.summary)}</p>
      ${details ? `<p class="rule-details">${escapeHtml(details)}</p>` : ""}
    </article>
  `;
}

function renderRuleOutput(rule) {
  if (rule.value === null || rule.value === undefined) {
    return `<div class="rule-output rule-output-empty">Data unavailable</div>`;
  }
  if (rule.id === "strategic_investors") return renderStrategicInvestors(rule.value);
  if (rule.id === "recent_cluster_purchase") return renderClusterPurchase(rule.value);
  if (rule.id === "constant_revenue_earnings_growth") return renderGrowthSeries(rule.value);
  if (typeof rule.value !== "object" || Array.isArray(rule.value)) {
    return `<div class="rule-output rule-output-primary">${escapeHtml(displayRuleValue(rule.value))}</div>`;
  }
  const entries = Object.entries(rule.value).filter(([, value]) => !Array.isArray(value) && typeof value !== "object");
  if (!entries.length) return `<div class="rule-output rule-output-empty">Data unavailable</div>`;
  return `
    <div class="rule-output rule-output-grid">
      ${entries.map(([key, value]) => ruleOutputItem(ruleValueLabel(key), displayRuleValue(value))).join("")}
    </div>
  `;
}

function renderStrategicInvestors(value) {
  const holders = Array.isArray(value?.holders) ? value.holders.slice(0, 3) : [];
  return `
    <div class="rule-output rule-output-stack">
      ${ruleOutputItem("Qualifying Investors", displayRuleValue(value?.qualifying_count))}
      ${holders.length ? `
        <div class="rule-output-list">
          ${holders.map((holder) => `
            <div>
              <strong>${escapeHtml(holder.holder || "Unknown investor")}</strong>
              <span>${escapeHtml(displayRuleValue(holder.percent_held))}</span>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function renderClusterPurchase(value) {
  const entries = ["distinct_insiders", "purchase_count", "total_value"]
    .filter((key) => value?.[key] !== null && value?.[key] !== undefined);
  const purchases = Array.isArray(value?.purchases) ? value.purchases.slice(0, 2) : [];
  return `
    <div class="rule-output rule-output-stack">
      <div class="rule-output-grid">
        ${entries.map((key) => ruleOutputItem(ruleValueLabel(key), displayRuleValue(value[key]))).join("")}
      </div>
      ${purchases.length ? `
        <div class="rule-output-list">
          ${purchases.map((purchase) => `
            <div>
              <strong>${escapeHtml(purchase.insider || "Unknown insider")}</strong>
              <span>${escapeHtml(displayRuleValue(purchase.value || purchase.date))}</span>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function renderGrowthSeries(value) {
  const entries = ["revenue_growth", "earnings_growth"];
  return `
    <div class="rule-output rule-output-series">
      ${entries.map((key) => `
        <div>
          <span>${escapeHtml(ruleValueLabel(key))}</span>
          <strong>${escapeHtml(displayRuleValue(value?.[key]))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function ruleOutputItem(label, value) {
  return `
    <div class="rule-output-item">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function ruleValueLabel(key) {
  return ruleValueLabels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayRuleValue(value) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  if (Array.isArray(value)) return value.length ? value.map(displayRuleValue).join(" → ") : "Unavailable";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function renderSources(notes) {
  if (!notes.length) return "";
  return `
    <details class="sources">
      <summary>
        <span>Sources & data notes</span>
        <strong>${notes.length}</strong>
      </summary>
      <div class="sources-list">
        ${notes.map((note) => `<p>${escapeHtml(note)}</p>`).join("")}
      </div>
    </details>
  `;
}

function activityColumn(title, items, renderer, emptyMessage) {
  return `
    <section class="activity-column">
      <div class="activity-column-head">
        <h3>${escapeHtml(title)}</h3>
        <span>${items.length}</span>
      </div>
      <div class="activity-list">
        ${items.length ? items.slice(0, 5).map(renderer).join("") : `<p class="activity-empty">${escapeHtml(emptyMessage)}</p>`}
      </div>
    </section>
  `;
}

function renderNewsItem(item) {
  const title = escapeHtml(item.title || "Untitled news item");
  const url = safeUrl(item.url);
  return `
    <article class="activity-item">
      <div class="activity-meta">
        <span>${escapeHtml(item.publisher || "Publisher unavailable")}</span>
        <time>${formatDate(item.published)}</time>
      </div>
      <h4>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</h4>
    </article>
  `;
}

function renderEarningsItem(item) {
  const hasEstimate = item.eps_estimate !== null && item.eps_estimate !== undefined;
  const hasSurprise = item.surprise_percent !== null && item.surprise_percent !== undefined;
  return `
    <article class="activity-item earnings-item">
      <div class="activity-meta">
        <span>Earnings report</span>
        <time>${formatDate(item.date)}</time>
      </div>
      <div class="earnings-values">
        ${earningsValue("Reported EPS", formatNumber(item.reported_eps))}
        ${hasEstimate || hasSurprise
          ? `${earningsValue("Estimate", formatNumber(item.eps_estimate))}
             ${earningsValue("Surprise", formatSignedPercent(item.surprise_percent))}`
          : `${earningsValue("Revenue", formatValue(item.revenue))}
             ${earningsValue("Net income", formatValue(item.net_income))}`}
      </div>
    </article>
  `;
}

function earningsValue(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
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
  return Number(value).toFixed(3);
}

function formatValue(value) {
  if (value === null || value === undefined) return "Unknown";
  const number = Number(value);
  if (number >= 1_000_000_000_000) return `$${(number / 1_000_000_000_000).toFixed(2)}T`;
  if (number >= 1_000_000_000) return `$${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `$${(number / 1_000).toFixed(2)}K`;
  return `$${number.toFixed(2)}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "Unknown";
  return Number(value).toFixed(2);
}

function formatSignedPercent(value) {
  if (value === null || value === undefined) return "Unknown";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(1)}%`;
}

function formatMarketPrice(value) {
  if (value === null || value === undefined) return "Unknown";
  const number = Number(value);
  return number >= 1000
    ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(number)
    : number.toFixed(2);
}

function formatMarketChange(change, percent) {
  if (change === null || change === undefined) return "Change unavailable";
  const number = Number(change);
  const percentText = percent === null || percent === undefined ? "" : ` (${number >= 0 ? "+" : ""}${(Number(percent) * 100).toFixed(2)}%)`;
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}${percentText}`;
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function safeUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function startMarketBackground(canvas) {
  if (!canvas || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const context = canvas.getContext("2d");
  const pointer = { x: -1000, y: -1000 };
  let nodes = [];
  let chartPoints = [];
  let width = 0;
  let height = 0;
  let animationFrame;

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const nodeCount = Math.max(22, Math.min(58, Math.floor((width * height) / 22000)));
    nodes = Array.from({ length: nodeCount }, (_, index) => ({
      x: ((index * 97) % width) + Math.random() * 40,
      y: ((index * 61) % height) + Math.random() * 40,
      vx: (Math.random() - 0.5) * 0.16,
      vy: (Math.random() - 0.5) * 0.16,
      size: index % 9 === 0 ? 2 : 1,
    }));

    chartPoints = Array.from({ length: 11 }, (_, index) => ({
      x: (width / 10) * index,
      y: height * (0.72 - index * 0.018) + (Math.random() - 0.5) * height * 0.12,
    }));
  }

  function drawChart(time) {
    context.beginPath();
    chartPoints.forEach((point, index) => {
      const wave = Math.sin(time * 0.00035 + index * 0.8) * 5;
      if (index === 0) context.moveTo(point.x, point.y + wave);
      else context.lineTo(point.x, point.y + wave);
    });
    context.strokeStyle = "rgba(255, 255, 255, 0.055)";
    context.lineWidth = 1;
    context.stroke();
  }

  function draw(time) {
    context.clearRect(0, 0, width, height);
    drawChart(time);

    for (const node of nodes) {
      const dx = node.x - pointer.x;
      const dy = node.y - pointer.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 140 && distance > 0) {
        node.vx += (dx / distance) * 0.003;
        node.vy += (dy / distance) * 0.003;
      }
      node.vx *= 0.995;
      node.vy *= 0.995;
      node.x += node.vx;
      node.y += node.vy;
      if (node.x < -10) node.x = width + 10;
      if (node.x > width + 10) node.x = -10;
      if (node.y < -10) node.y = height + 10;
      if (node.y > height + 10) node.y = -10;
    }

    for (let first = 0; first < nodes.length; first += 1) {
      for (let second = first + 1; second < nodes.length; second += 1) {
        const distance = Math.hypot(nodes[first].x - nodes[second].x, nodes[first].y - nodes[second].y);
        if (distance > 145) continue;
        context.beginPath();
        context.moveTo(nodes[first].x, nodes[first].y);
        context.lineTo(nodes[second].x, nodes[second].y);
        context.strokeStyle = `rgba(255, 255, 255, ${0.055 * (1 - distance / 145)})`;
        context.lineWidth = 1;
        context.stroke();
      }
    }

    for (const node of nodes) {
      const pointerDistance = Math.hypot(node.x - pointer.x, node.y - pointer.y);
      context.beginPath();
      context.arc(node.x, node.y, node.size, 0, Math.PI * 2);
      context.fillStyle = pointerDistance < 150 ? "rgba(255, 255, 255, 0.58)" : "rgba(255, 255, 255, 0.18)";
      context.fill();
    }

    animationFrame = window.requestAnimationFrame(draw);
  }

  window.addEventListener("resize", resize);
  window.addEventListener("pointermove", (event) => {
    pointer.x = event.clientX;
    pointer.y = event.clientY;
  });
  window.addEventListener("pointerleave", () => {
    pointer.x = -1000;
    pointer.y = -1000;
  });

  resize();
  animationFrame = window.requestAnimationFrame(draw);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      window.cancelAnimationFrame(animationFrame);
    } else {
      animationFrame = window.requestAnimationFrame(draw);
    }
  });
}
