// Cloudflare Worker that lets the GitHub Pages dashboard ask Claude questions
// without exposing your API key. The page runs the search tools itself; this
// Worker only relays each step to the Claude API and back.
//
// Settings (Cloudflare dashboard > Worker > Settings > Variables):
//   ANTHROPIC_API_KEY  (secret)  your Claude API key
//   ALLOWED_ORIGIN     e.g. https://biggarlab.github.io
//   DAILY_LIMIT        optional, max relayed calls per day (default 300)
//   MODEL              optional, default claude-sonnet-5-5
// Optional KV namespace binding named LIMITS enables the daily limit.

const MAX_BODY = 250_000;

function cors(origin, allowed) {
  return {
    "Access-Control-Allow-Origin": origin === allowed ? origin : allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Vary": "Origin",
  };
}

export default {
  async fetch(request, env) {
    const allowed = env.ALLOWED_ORIGIN || "https://biggarlab.github.io";
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin, allowed);
    if (request.method === "OPTIONS") return new Response(null, { headers });
    if (request.method !== "POST") return new Response("POST only", { status: 405, headers });
    if (origin !== allowed) return new Response("Forbidden", { status: 403, headers });

    const raw = await request.text();
    if (raw.length > MAX_BODY) return new Response("Request too large", { status: 413, headers });
    let body;
    try { body = JSON.parse(raw); } catch { return new Response("Bad JSON", { status: 400, headers }); }
    if (!Array.isArray(body.messages) || body.messages.length > 30) return new Response("Bad request", { status: 400, headers });

    if (env.LIMITS) {
      const day = new Date().toISOString().slice(0, 10);
      const used = parseInt((await env.LIMITS.get(day)) || "0", 10);
      if (used >= parseInt(env.DAILY_LIMIT || "300", 10)) return new Response("Daily limit reached", { status: 429, headers });
      await env.LIMITS.put(day, String(used + 1), { expirationTtl: 172800 });
    }

    const upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({
        model: env.MODEL || "claude-sonnet-5-5",
        max_tokens: 2500,
        messages: body.messages,
        ...(Array.isArray(body.tools) && body.tools.length ? { tools: body.tools.slice(0, 8) } : {}),
      }),
    });
    const text = await upstream.text();
    return new Response(text, { status: upstream.status, headers: { ...headers, "content-type": "application/json" } });
  },
};
