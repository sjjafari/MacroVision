import { getBackendUrl } from "@/lib/api/backend-url";
import { rewriteUpstreamRedirect } from "@/lib/api/redirect";

export const dynamic = "force-dynamic";

const REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "if-match",
  "if-none-match",
] as const;

const RESPONSE_HEADERS = [
  "cache-control",
  "content-language",
  "content-type",
  "etag",
  "last-modified",
  "retry-after",
  "allow",
] as const;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function safeRequestHeaders(request: Request): Headers {
  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  return headers;
}

function safeResponseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  headers.set("x-content-type-options", "nosniff");
  return headers;
}

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  try {
    const backend = getBackendUrl();
    const backendBase = new URL(backend);
    const { path } = await context.params;
    const requestUrl = new URL(request.url);
    const basePath = backend.pathname === "/" ? "" : backend.pathname;
    backend.pathname = `${basePath}/api/v1/${path.map(encodeURIComponent).join("/")}`;
    backend.search = requestUrl.search;

    const body =
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer();
    const upstream = await fetch(backend, {
      method: request.method,
      headers: safeRequestHeaders(request),
      body,
      redirect: "manual",
      cache: "no-store",
    });
    const headers = safeResponseHeaders(upstream);
    const location = upstream.headers.get("location");
    if (location && upstream.status >= 300 && upstream.status < 400) {
      const safeLocation = rewriteUpstreamRedirect(location, backend, backendBase);
      if (!safeLocation) {
        return Response.json(
          {
            error: {
              code: "unsafe_upstream_redirect",
              message: "تغییر مسیر Backend خارج از محدودهٔ مجاز بود.",
            },
          },
          { status: 502 },
        );
      }
      headers.set("location", safeLocation);
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  } catch (error) {
    const message =
      error instanceof Error && error.message.includes("MACROVISION_BACKEND_URL")
        ? "پیکربندی Backend معتبر نیست."
        : "ارتباط امن با Backend برقرار نشد.";
    return Response.json(
      {
        error: {
          code: "upstream_unavailable",
          message,
        },
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
export const HEAD = proxy;
