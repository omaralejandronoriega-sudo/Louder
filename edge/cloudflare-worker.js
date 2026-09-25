const PAGES_ORIGIN = "https://omaralejandronoriega-sudo.github.io";
const PAGES_BASE = "/Louder";

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
    pathname.startsWith("/radar-2026/")
  );
}

export default {
  async fetch(request) {
    const incoming = new URL(request.url);

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
