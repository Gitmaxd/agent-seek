(() => {
  const form = document.getElementById("search-form");
  const qEl = document.getElementById("q");
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");

  /** Fixed UI defaults — agents still pass k / max_candidates / mode via API. */
  const UI_K = 10;
  const UI_MAX_CANDIDATES = 50;
  const UI_MODE = "snip";
  const DEFAULT_TITLE = document.title;
  const resultsHeading = document.getElementById("results-heading");

  function setDocTitle(query) {
    document.title = query ? `${query} — Agent Seek` : DEFAULT_TITLE;
  }

  function setResultsHeading(query) {
    if (!resultsHeading) return;
    if (query) {
      resultsHeading.textContent = `Results for ${query}`;
      resultsHeading.hidden = false;
    } else {
      resultsHeading.textContent = "Results";
      resultsHeading.hidden = true;
    }
  }


  function apiKey() {
    return (window.AGENT_SEEK_CONFIG && window.AGENT_SEEK_CONFIG.apiKey) || "";
  }

  function setStatus(msg, isError) {
    if (!msg) {
      statusEl.hidden = true;
      statusEl.textContent = "";
      return;
    }
    statusEl.hidden = false;
    statusEl.textContent = msg;
    statusEl.classList.toggle("error", !!isError);
  }

  function isDemoExhausted(data) {
    const code = (data && data.code) || (data && data.error && data.error.code) || "";
    if (code === "DEMO_EXHAUSTED") return true;
    const msg =
      (data && data.error && data.error.message) ||
      (data && data.message) ||
      (typeof data?.detail === "string" ? data.detail : "") ||
      "";
    return /demo allowance|demo complete|free demo/i.test(String(msg));
  }

  function showDemoExhaustedDialog() {
    const dialog = document.getElementById("demo-exhausted");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    document.getElementById("demo-exhausted-close")?.focus();
  }

  function hideDemoExhaustedDialog() {
    const dialog = document.getElementById("demo-exhausted");
    if (!dialog) return;
    if (typeof dialog.close === "function" && dialog.open) {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  document.getElementById("demo-exhausted-close")?.addEventListener("click", hideDemoExhaustedDialog);
  document.getElementById("demo-exhausted")?.addEventListener("click", (e) => {
    if (e.target && e.target.id === "demo-exhausted") hideDemoExhaustedDialog();
  });

  function scorePct(score) {
    const n = Number(score) || 0;
    return Math.round(n * 100);
  }

  // filled = clamp(round(score * 10), 0, 10) — API score 0–1 → 10-box meter (0.85 → 9)
  function scoreBoxes(score) {
    const n = Number(score) || 0;
    return Math.max(0, Math.min(10, Math.round(n * 10)));
  }

  const SIGNAL_LABELS = {
    answerability: "Answers the query",
    authority: "Source authority",
    on_topic: "On topic",
    states_sought_fact: "States the fact",
    subject_match: "Right subject",
    spam: "Spam risk",
    prompt_injection: "Injection risk",
  };
  const SIGNAL_ORDER = [
    "answerability",
    "authority",
    "on_topic",
    "states_sought_fact",
    "subject_match",
    "spam",
    "prompt_injection",
  ];

  function boxesHtml(filled, { warn = false } = {}) {
    return Array.from({ length: 10 }, (_, i) => {
      const on = i < filled;
      let cls = "score-box";
      if (on) cls += warn ? " filled-warn" : " filled";
      return `<span class="${cls}"></span>`;
    }).join("");
  }

  function buildSignalRows(signals) {
    if (!signals || typeof signals !== "object") return "";
    const rows = [];
    for (const key of SIGNAL_ORDER) {
      if (!(key in signals)) continue;
      const val = Number(signals[key]);
      if (!Number.isFinite(val)) continue;
      const filled = scoreBoxes(val);
      const warn = key === "spam" || key === "prompt_injection";
      const label = SIGNAL_LABELS[key] || key;
      rows.push(
        `<div class="score-card-row">` +
          `<span class="score-card-label">${escapeHtml(label)}</span>` +
          `<span class="score-card-meter" aria-hidden="true">${boxesHtml(filled, { warn })}</span>` +
          `<span class="score-card-pct">${Math.round(val * 100)}%</span>` +
        `</div>`
      );
    }
    return rows.join("");
  }

  // filled = clamp(round(score * 10), 0, 10) — API score 0–1 → 10-box meter
  function createScoreMeter(r) {
    const score = Number(r && r.score) || 0;
    const filled = scoreBoxes(score);
    const pct = scorePct(score);
    const wrap = document.createElement("div");
    wrap.className = "score-meter-wrap";

    const meter = document.createElement("div");
    meter.className = "score-meter";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `Relevance ${filled} of 10`);
    meter.setAttribute("tabindex", "0");
    meter.innerHTML = boxesHtml(filled);

    const card = document.createElement("div");
    card.className = "score-card";
    card.setAttribute("role", "tooltip");
    const signalRows = buildSignalRows(r && r.signals);
    const rawRank = r && r.raw_rank != null ? r.raw_rank : "—";
    card.innerHTML =
      `<div class="score-card-header">` +
        `<span class="score-card-title">Relevance</span>` +
        `<span class="score-card-big">${filled}<span class="score-card-of">/10</span></span>` +
        `<span class="score-card-percent">${pct}%</span>` +
      `</div>` +
      (signalRows ? `<div class="score-card-body">${signalRows}</div>` : "") +
      `<div class="score-card-footer">SERP #${escapeHtml(String(rawRank))}</div>`;

    wrap.appendChild(meter);
    wrap.appendChild(card);

    let open = false;
    const show = () => {
      open = true;
      wrap.classList.add("is-open");
    };
    const hide = () => {
      open = false;
      wrap.classList.remove("is-open");
    };
    const toggle = (e) => {
      // Mobile tap toggle; don't steal title-link clicks (meter is separate).
      if (e && e.type === "click") e.preventDefault();
      if (open) hide();
      else show();
    };

    meter.addEventListener("mouseenter", show);
    meter.addEventListener("focus", show);
    wrap.addEventListener("mouseleave", hide);
    meter.addEventListener("blur", (e) => {
      // Keep open if focus moved into the card
      if (wrap.contains(e.relatedTarget)) return;
      hide();
    });
    meter.addEventListener("click", toggle);
    meter.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hide();
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });

    return wrap;
  }

  function renderList(items) {
    resultsEl.innerHTML = "";
    if (!items || !items.length) {
      resultsEl.innerHTML = '<p class="status">No results.</p>';
      return;
    }
    for (const r of items) {
      const div = document.createElement("div");
      div.className = "result";
      div.innerHTML = `
        <div class="url">${escapeHtml(r.url || "")}</div>
        <a class="title" href="${escapeAttr(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.title || r.url)}</a>
        <p class="snippet">${escapeHtml(r.snippet || "")}</p>`;
      div.appendChild(createScoreMeter(r));
      resultsEl.appendChild(div);
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }


  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = qEl.value.trim();
    if (!q) return;
    const key = apiKey();
    if (!key) {
      document.querySelector(".hero")?.classList.add("has-results");
      setDocTitle(q);
      setResultsHeading(q);
      setStatus("Missing Agent Seek API key (config.js).", true);
      return;
    }
    document.querySelector(".hero")?.classList.add("has-results");
    setDocTitle(q);
    setResultsHeading(q);
    setStatus("Searching…");
    resultsEl.innerHTML = "";
    try {
      const body = {
        q,
        k: UI_K,
        max_candidates: UI_MAX_CANDIDATES,
        mode: UI_MODE,
      };
      const res = await fetch("/v1/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${key}`,
        },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail =
          (data.error && data.error.message) ||
          (typeof data.detail === "string"
            ? data.detail
            : data.detail
              ? JSON.stringify(data.detail)
              : `Error ${res.status}`);
        if (isDemoExhausted(data) || /demo allowance|demo complete|free demo/i.test(String(detail))) {
          showDemoExhaustedDialog();
        }
        setStatus(detail, true);
        return;
      }
      setStatus("");
      document.querySelector(".hero")?.classList.add("has-results");
      if ((!data.results || !data.results.length) && data.raw_results?.length) {
        setStatus("Showing discover order (gates returned empty)");
        renderList(data.raw_results);
      } else {
        renderList(data.results);
      }
    } catch (err) {
      setStatus(String(err.message || err), true);
    }
  });
})();
