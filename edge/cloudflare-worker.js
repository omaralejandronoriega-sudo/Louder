const PAGES_ORIGIN = "https://artistas.loudermx.com";
const PAGES_BASE = "";
const GITHUB_OWNER = "omaralejandronoriega-sudo";
const ARTIST_PUBLIC_ORIGIN = "https://artistas.loudermx.com";

function githubUrl(requestUrl) {
  const incoming = new URL(requestUrl);
  const target = new URL(PAGES_ORIGIN);
  target.pathname = PAGES_BASE + incoming.pathname;
  target.search = incoming.search;
  return target;
}

function publicLocation(location, requestUrl) {
  if (!location) return location;
  const incoming = new URL(requestUrl);
  const resolved = new URL(location, PAGES_ORIGIN);
  if (resolved.hostname !== new URL(PAGES_ORIGIN).hostname) return location;
  const path = resolved.pathname.startsWith(PAGES_BASE)
    ? resolved.pathname.slice(PAGES_BASE.length) || "/"
    : resolved.pathname;
  return incoming.origin + path + resolved.search + resolved.hash;
}

function isStaticSection(pathname) {
  return (
    pathname === "/artistas" ||
    pathname.startsWith("/artistas/") ||
    pathname === "/radar-2026" ||
    pathname.startsWith("/radar-2026/") ||
    pathname === "/control" ||
    pathname.startsWith("/control/")
  );
}

function isAiRoute(pathname) {
  return (
    pathname === "/control/api/ai" ||
    pathname === "/artistas/_control/api/ai"
  );
}

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

async function verifyGithubOwner(token) {
  if (!token) return false;
  try {
    const res = await fetch("https://api.github.com/user", {
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${token}`,
        "user-agent": "Louder-Control",
        "x-github-api-version": "2022-11-28",
      },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    if (!res.ok) return false;
    const user = await res.json();
    return String(user?.login || "").toLowerCase() === GITHUB_OWNER.toLowerCase();
  } catch (_) {
    return false;
  }
}

function louderInstructions(task) {
  const taskContext = task
    ? `
PROJECT: ${task.project || ""}
AREA: ${task.area || ""}
TASK: ${task.title || ""}
PROJECT CONTEXT: ${task.summary || ""}
OBJECTIVE: ${task.objective || ""}
NOTES: ${task.notes || ""}
`
    : "";

  return `You are Louder Control AI, an embedded operations assistant for the Louder music/media project.
Work in Spanish unless the user asks otherwise. Be concise, operational, and specific.
Do not merely restate a checklist. Investigate, reason, and produce a usable result.
Use web search when current public information materially improves the answer.
When the task can be advanced with concrete instructions, commands, configuration, copy, analysis, or a diagnostic, produce those directly.
Do not claim that you executed an external action unless the system actually performed it.
If a task requires access to a connected account or tool that is not available to this API session, say exactly what access is missing and give the smallest next action needed.
For web/performance work, prioritize measurable evidence: TTFB, HTTP status, Core Web Vitals, render-blocking resources, request counts, cron/query load, CPU/memory and origin requests. Avoid changes that add unnecessary load to WordPress.
For Louder editorial/social work, keep the user's established Louder tone and avoid generic AI phrasing.
At the end, include a short "Estado" line: RESUELTO, AVANZADO, or BLOQUEADO, plus one sentence explaining why.
${taskContext}`;
}

async function handleAi(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "METHOD_NOT_ALLOWED" }, 405, { allow: "POST" });
  }

  if (!env.OPENAI_API_KEY) {
    return jsonResponse({
      error: "AI_NOT_CONFIGURED",
      message: "Falta configurar OPENAI_API_KEY como secreto del Worker.",
    }, 503);
  }

  const githubToken = request.headers.get("x-louder-github-token") || "";
  const authorized = await verifyGithubOwner(githubToken);
  if (!authorized) {
    return jsonResponse({
      error: "UNAUTHORIZED",
      message: "Activa la ejecución directa con tu sesión de GitHub antes de usar Louder IA.",
    }, 401);
  }

  let payload;
  try {
    payload = await request.json();
  } catch (_) {
    return jsonResponse({ error: "INVALID_JSON" }, 400);
  }

  const message = String(payload?.message || "").trim();
  const task = payload?.task && typeof payload.task === "object" ? payload.task : null;
  const history = Array.isArray(payload?.history)
    ? payload.history
        .slice(-10)
        .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
        .map((m) => ({ role: m.role, content: m.content.slice(0, 12000) }))
    : [];

  if (!message) {
    return jsonResponse({ error: "EMPTY_MESSAGE" }, 400);
  }

  const body = {
    model: env.OPENAI_MODEL || "gpt-6-sol",
    instructions: louderInstructions(task),
    input: [...history, { role: "user", content: message }],
    stream: true,
    store: false,
    reasoning: { effort: "medium" },
    text: { verbosity: "medium" },
    tools: [{ type: "web_search" }],
    max_tool_calls: 6,
    max_output_tokens: 5000,
    safety_identifier: "louder-control-owner",
  };

  const clientRequestId = crypto.randomUUID();
  const upstream = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "content-type": "application/json",
      accept: "text/event-stream",
      "x-client-request-id": clientRequestId,
    },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    let detail = "";
    try {
      const err = await upstream.json();
      detail = err?.error?.message || err?.message || "";
    } catch (_) {}
    return jsonResponse({
      error: "OPENAI_ERROR",
      status: upstream.status,
      message: detail || "OpenAI no pudo procesar la solicitud.",
      request_id: upstream.headers.get("x-request-id") || clientRequestId,
    }, upstream.status);
  }

  const headers = new Headers(upstream.headers);
  headers.set("content-type", "text/event-stream; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-accel-buffering", "no");
  headers.set("x-louder-ai", "openai-responses");
  headers.set("x-louder-client-request-id", clientRequestId);
  return new Response(upstream.body, {
    status: 200,
    headers,
  });
}

export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);

    if (isAiRoute(incoming.pathname)) {
      return handleAi(request, env);
    }

    if (incoming.pathname === "/artistas" || incoming.pathname.startsWith("/artistas/")) {
      const target = new URL(ARTIST_PUBLIC_ORIGIN);
      target.pathname = incoming.pathname;
      target.search = incoming.search;
      return Response.redirect(target.toString(), 301);
    }

    // Only selected static sections are served from GitHub Pages.
    // Everything else keeps going to the existing Louder origin.
    if (
      (request.method !== "GET" && request.method !== "HEAD") ||
      !isStaticSection(incoming.pathname)
    ) {
      return fetch(request);
    }

    try {
      const upstreamHeaders = new Headers();
      for (const name of ["accept", "accept-language", "user-agent", "if-none-match", "if-modified-since"]) {
        const value = request.headers.get(name);
        if (value) upstreamHeaders.set(name, value);
      }
      const upstreamRequest = new Request(githubUrl(request.url), {
        method: request.method,
        headers: upstreamHeaders,
        redirect: "manual",
      });
      const upstream = await fetch(upstreamRequest, {
        cf: {
          cacheEverything: true,
          cacheTtl: incoming.pathname.match(/\.(css|js|svg|webp|avif|png|jpg|jpeg|json)$/i)
            ? 86400
            : 300,
        },
      });

      // Fail safe: if GitHub is unavailable or a page is missing,
      // keep the current WordPress origin available.
      if (upstream.status >= 500 || upstream.status === 404) {
        return fetch(request);
      }

      const headers = new Headers(upstream.headers);
      headers.set("X-Louder-Static-Origin", "github-pages");
      headers.set(
        "Cache-Control",
        incoming.pathname.match(/\.(css|js|svg|webp|avif|png|jpg|jpeg|json)$/i)
          ? "public, max-age=86400"
          : "public, max-age=300, stale-while-revalidate=3600"
      );

      const location = headers.get("Location");
      if (location) {
        headers.set("Location", publicLocation(location, request.url));
      }

      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    } catch (_) {
      return fetch(request);
    }
  },
};
