import { NextRequest, NextResponse } from "next/server";
import { authorizeTrustedHeaders, securityMode } from "@/lib/security/request-auth";

const publicPaths=new Set(["/fa/about","/fa/methodology"]);
const protectedPrefixes=["/fa"];
export function proxy(request:NextRequest) {
  const response=NextResponse.next();
  response.headers.set("x-content-type-options","nosniff");
  response.headers.set("referrer-policy","strict-origin-when-cross-origin");
  response.headers.set("permissions-policy","camera=(), microphone=(), geolocation=()");
  if(securityMode()!=="production") return response;
  if(protectedPrefixes.some(prefix=>request.nextUrl.pathname.startsWith(prefix)) && !publicPaths.has(request.nextUrl.pathname)) {
    const identity=authorizeTrustedHeaders(request.headers,request.nextUrl.pathname.startsWith("/fa/research")?"research":"reader");
    if(!identity) return new NextResponse("Authentication required",{status:401,headers:{"cache-control":"no-store"}});
  }
  return response;
}
export const config={matcher:["/fa/:path*"]};
