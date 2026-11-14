import { NextRequest, NextResponse } from "next/server";
import { authorizeTrustedHeaders, securityMode } from "@/lib/security/request-auth";

const exactPublicPaths = new Set(["/fa/about", "/fa/methodology", "/fa/indicators"]);
export function isPublicPath(pathname: string) {
  return exactPublicPaths.has(pathname) || pathname.startsWith("/fa/indicators/");
}

export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set("x-content-type-options", "nosniff");
  response.headers.set("referrer-policy", "strict-origin-when-cross-origin");
  response.headers.set("permissions-policy", "camera=(), microphone=(), geolocation=()");
  if (securityMode() !== "production") return response;
  if (request.nextUrl.pathname.startsWith("/fa") && !isPublicPath(request.nextUrl.pathname)) {
    const required = request.nextUrl.pathname.startsWith("/fa/research") ? "research" : "reader";
    const identity = authorizeTrustedHeaders(request.headers, required);
    if (!identity) return new NextResponse("Authentication required", { status: 401, headers: { "cache-control": "no-store" } });
  }
  return response;
}
export const config = { matcher: ["/fa/:path*"] };
