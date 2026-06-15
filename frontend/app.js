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

    ${(data.source_notes || []).map((note) => `<div class="note">${escapeHtml(note)}</div>`).join("")}
  `;
  resultsNode.hidden = false;
  screen.classList.add("has-results");
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

function renderRule(rule) {
  return `
    <article class="rule">
      <div class="rule-head">
        <h3>${escapeHtml(rule.name)}</h3>
        <span class="pill ${escapeHtml(rule.status)}">${escapeHtml(rule.status)}</span>
      </div>
      <p>${escapeHtml(rule.summary)}</p>
      ${rule.target ? `<p><strong>Target:</strong> ${escapeHtml(rule.target)}</p>` : ""}
      ${rule.details ? `<p class="rule-details">${escapeHtml(rule.details)}</p>` : ""}
      ${rule.value !== null && rule.value !== undefined ? `<div class="rule-data">${escapeHtml(JSON.stringify(rule.value))}</div>` : ""}
    </article>
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
        ${items.length ? items.slice(0, 3).map(renderer).join("") : `<p class="activity-empty">${escapeHtml(emptyMessage)}</p>`}
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
