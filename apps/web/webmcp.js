/* WebMCP: register in-page tools for browser agents.
 * Prefer document.modelContext; navigator.modelContext is a compatibility fallback.
 */
(() => {
  function apiKey() {
    return (window.AGENT_SEEK_CONFIG && window.AGENT_SEEK_CONFIG.apiKey) || "";
  }

  async function searchWeb({ q, k, max_candidates, mode }) {
    const query = String(q || "").trim();
    if (!query) {
      return { content: [{ type: "text", text: "q is required" }], isError: true };
    }
    const key = apiKey();
    const headers = { "Content-Type": "application/json" };
    if (key) headers.Authorization = `Bearer ${key}`;
    const res = await fetch("/v1/search", {
      method: "POST",
      headers,
      body: JSON.stringify({
        q: query,
        k: Number(k) || 10,
        max_candidates: Number(max_candidates) || 50,
        mode: mode || "snip",
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = (data.error && data.error.message) || data.message || `Error ${res.status}`;
      return { content: [{ type: "text", text: msg }], isError: true };
    }
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
      structuredContent: data,
    };
  }

  const tools = [
    {
      name: "search_web",
      description: "Search the web with Agent Seek ranked results (You.com discover plus TypeSafe Jev cascade; default mode=snip, title/URL/snippet). Pass mode=deep for Stage A survivor fetch (cap 12).",
      inputSchema: {
        type: "object",
        properties: {
          q: { type: "string", description: "Search query (1-500 characters)" },
          k: { type: "integer", description: "Number of ranked results (1-25)", default: 10 },
          max_candidates: { type: "integer", description: "Discover cap (1-100)", default: 50 },
          mode: { type: "string", description: "snip (default) ranks title/URL/snippet; deep fetches Stage A survivors (cap 12)", enum: ["deep", "snip"], default: "snip" },
        },
        required: ["q"],
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
      execute: searchWeb,
    },
    {
      name: "get_service_health",
      description: "Return Agent Seek liveness and prototype version for browser agents.",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true, destructiveHint: false },
      async execute() {
        const res = await fetch("/health");
        const data = await res.json();
        return { content: [{ type: "text", text: JSON.stringify(data) }], structuredContent: data };
      },
    },
  ];

  function registerAll(ctx) {
    if (!ctx || typeof ctx.registerTool !== "function") return false;
    for (const tool of tools) {
      try {
        ctx.registerTool(tool);
      } catch (_err) {
        // Older drafts used (definition, execute).
        try {
          ctx.registerTool(
            {
              name: tool.name,
              description: tool.description,
              inputSchema: tool.inputSchema,
            },
            tool.execute
          );
        } catch (_err2) {
          /* ignore unsupported browser */
        }
      }
    }
    return true;
  }

  function boot() {
    if (registerAll(document.modelContext)) return;
    registerAll(navigator.modelContext);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
