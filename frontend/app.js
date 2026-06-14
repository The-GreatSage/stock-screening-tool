const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker");
const statusNode = document.querySelector("#status");
const resultsNode = document.querySelector("#results");
const submitButton = form.querySelector("button[type='submit']");
const screen = document.querySelector(".screen");
const backgroundCanvas = document.querySelector("#market-background");

startMarketBackground(backgroundCanvas);

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
