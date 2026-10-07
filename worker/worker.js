// Cloudflare Worker: lets the public dashboard use one AI key without exposing it.
// The page runs the Faculty data tools itself; this Worker only relays each step to the AI provider.
// It speaks the Claude (Anthropic) message format to the page and can translate to OpenAI.
//
// Worker settings (Cloudflare dashboard > your Worker > Settings > Variables and Secrets):
//   PROVIDER          "openai" or "anthropic"                         (plain text, default openai)
//   OPENAI_API_KEY    your OpenAI or Azure OpenAI key                  (secret, if PROVIDER=openai)
//   OPENAI_BASE_URL   only for Azure, e.g. https://<name>.services.ai.azure.com/openai/v1 (plain text)
//   ANTHROPIC_API_KEY your Claude key                                  (secret, if PROVIDER=anthropic)
//   MODEL             model name, e.g. gpt-5-mini or claude-sonnet-5-5 (plain text, optional; on Azure, the deployment name)
//   ALLOWED_ORIGIN    https://biggarlab.github.io                       (plain text)
//   PASSCODE          shared passcode people type once                  (secret, optional but recommended)
//   DAILY_LIMIT       max questions per day, default 200                (plain text, optional; needs a KV binding named LIMITS)

const MAX_BODY = 400_000;

function corsHeaders(origin, allowed) {
  return {
    "Access-Control-Allow-Origin": origin === allowed ? origin : allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-passcode",
    "Vary": "Origin",
  };
}
const json = (obj, status, headers) => new Response(JSON.stringify(obj), { status, headers: { ...headers, "content-type": "application/json" } });

export default {
  async fetch(request, env) {
    const allowed = env.ALLOWED_ORIGIN || "https://biggarlab.github.io";
    const origin = request.headers.get("Origin") || "";
    const headers = corsHeaders(origin, allowed);
    if (request.method === "OPTIONS") return new Response(null, { headers });
    if (request.method !== "POST") return json({ error: { message: "POST only" } }, 405, headers);
    if (origin !== allowed) return json({ error: { message: "Forbidden" } }, 403, headers);
    if (env.PASSCODE && request.headers.get("x-passcode") !== env.PASSCODE)
      return json({ error: { type: "passcode", message: "Passcode required" } }, 401, headers);

    const raw = await request.text();
    if (raw.length > MAX_BODY) return json({ error: { message: "Conversation too long. Start a new chat." } }, 413, headers);
    let body;
    try { body = JSON.parse(raw); } catch { return json({ error: { message: "Bad JSON" } }, 400, headers); }
    if (!Array.isArray(body.messages) || body.messages.length > 60) return json({ error: { message: "Bad request" } }, 400, headers);

    // Daily cap counts new questions only (a user turn that is plain text), not tool round trips.
    const last = body.messages[body.messages.length - 1];
    if (env.LIMITS && typeof last?.content === "string") {
      const day = new Date().toISOString().slice(0, 10);
      const used = parseInt((await env.LIMITS.get(day)) || "0", 10);
      if (used >= parseInt(env.DAILY_LIMIT || "200", 10)) return json({ error: { message: "Daily limit reached" } }, 429, headers);
      await env.LIMITS.put(day, String(used + 1), { expirationTtl: 172800 });
    }

    try {
      const out = (env.PROVIDER || "openai") === "anthropic" ? await viaAnthropic(body, env) : await viaOpenAI(body, env);
      return json(out, 200, headers);
    } catch (e) {
      return json({ error: { message: String(e.message || e).slice(0, 400) } }, e.status || 502, headers);
    }
  },
};

// ---------------------------------------------------------------- Claude
async function viaAnthropic(body, env) {
  const tools = [...(body.tools || []).slice(0, 10)];
  if (body.web) tools.push({ type: "web_search_20250305", name: "web_search", max_uses: 5,
    user_location: { type: "approximate", city: "Ottawa", region: "Ontario", country: "CA", timezone: "America/Toronto" } });
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model: env.MODEL || "claude-sonnet-5-5", max_tokens: 4000, system: body.system, messages: body.messages, ...(tools.length ? { tools } : {}) }),
  });
  const d = await r.json();
  if (!r.ok) throw Object.assign(new Error(d.error?.message || `Claude error ${r.status}`), { status: r.status === 401 ? 502 : r.status });
  return d;
}

// ---------------------------------------------------------------- OpenAI (Responses API), translated to the Claude shape
function toOpenAIInput(messages) {
  const input = [];
  for (const m of messages) {
    if (typeof m.content === "string") { input.push({ role: m.role, content: m.content }); continue; }
    for (const b of m.content || []) {
      if (b.type === "text" && b.text) input.push({ role: m.role, content: b.text });
      else if (b.type === "tool_use") input.push({ type: "function_call", call_id: b.id, name: b.name, arguments: JSON.stringify(b.input || {}) });
      else if (b.type === "tool_result") input.push({ type: "function_call_output", call_id: b.tool_use_id, output: typeof b.content === "string" ? b.content : JSON.stringify(b.content) });
      // server_tool_use and web search results are informational only; skip them
    }
  }
  return input;
}

async function openaiCall(env, payload) {
  const base = (env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
  const azure = /azure\.com/i.test(base);
  const r = await fetch(`${base}/responses`, {
    method: "POST",
    headers: { ...(azure ? { "api-key": env.OPENAI_API_KEY } : { "Authorization": `Bearer ${env.OPENAI_API_KEY}` }), "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  let d = {};
  try { d = await r.json(); } catch {}
  return { r, d };
}

async function viaOpenAI(body, env) {
  const fns = (body.tools || []).slice(0, 10).map(t => ({ type: "function", name: t.name, description: t.description, parameters: t.input_schema || { type: "object", properties: {} } }));
  const payload = { model: env.MODEL || "gpt-5-mini", instructions: body.system || undefined, input: toOpenAIInput(body.messages), max_output_tokens: 6000, store: false };
  const withWeb = body.web && env.WEB_SEARCH !== "off";
  let { r, d } = await openaiCall(env, { ...payload, tools: withWeb ? [...fns, { type: "web_search" }] : fns });
  // Some deployments (often Azure) don't offer web search: retry once without it and tell the model.
  if (!r.ok && withWeb && r.status === 400) {
    ({ r, d } = await openaiCall(env, { ...payload, tools: fns,
      instructions: (body.system || "") + "\n\nWeb search is not available on this deployment. Say so if a question needs current outside information." }));
  }
  if (!r.ok) throw Object.assign(new Error(d.error?.message || `OpenAI error ${r.status}`), { status: r.status === 401 || r.status === 403 ? 502 : r.status });
  const content = [];
  let calls = 0;
  for (const item of d.output || []) {
    if (item.type === "message") {
      const text = (item.content || []).filter(c => c.type === "output_text").map(c => c.text).join("");
      if (text) content.push({ type: "text", text });
    } else if (item.type === "function_call") {
      calls++;
      let input = {};
      try { input = JSON.parse(item.arguments || "{}"); } catch {}
      content.push({ type: "tool_use", id: item.call_id, name: item.name, input });
    } else if (item.type === "web_search_call") {
      content.push({ type: "server_tool_use", id: item.id, name: "web_search", input: { query: item.action?.query || "" } });
    }
  }
  const stop = calls ? "tool_use" : d.status === "incomplete" ? "max_tokens" : "end_turn";
  return { content, stop_reason: stop, model: d.model };
}
