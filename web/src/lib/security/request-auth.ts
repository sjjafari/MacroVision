import "server-only";

import { timingSafeEqual } from "node:crypto";
import { headers } from "next/headers";

export type MacroVisionRole = "reader" | "research" | "operator";
const rank: Record<MacroVisionRole,number> = {reader:1,research:2,operator:3};

export function securityMode() {
  return process.env.MACROVISION_SECURITY_MODE === "production" ? "production" : "private_preview";
}
function equalSecret(actual:string,expected:string) {
  const a=Buffer.from(actual),b=Buffer.from(expected);
  return a.length===b.length && timingSafeEqual(a,b);
}
function configuredRole(user:string): MacroVisionRole | null {
  const lists: Array<[MacroVisionRole,string|undefined]> = [
    ["operator",process.env.MACROVISION_OPERATOR_USERS],
    ["research",process.env.MACROVISION_RESEARCH_USERS],
    ["reader",process.env.MACROVISION_READER_USERS],
  ];
  for(const [role,value] of lists) if((value??"").split(",").map(x=>x.trim().toLowerCase()).filter(Boolean).includes(user.toLowerCase())) return role;
  return null;
}
export function authorizeTrustedHeaders(source:Headers,required:MacroVisionRole) {
  if(securityMode()==="private_preview") return {user:"local-preview",role:"operator" as const};
  const expected=process.env.MACROVISION_TRUSTED_PROXY_SECRET??"";
  const actual=source.get("x-macrovision-proxy-secret")??"";
  const user=source.get("x-auth-request-user")?.trim()??"";
  if(expected.length<32||!actual||!equalSecret(actual,expected)||!user) return null;
  const role=configuredRole(user);
  if(!role||rank[role]<rank[required]) return null;
  return {user,role};
}
export function authorizeMutationHeaders(source:Headers,required:MacroVisionRole) {
  const identity=authorizeTrustedHeaders(source,required);
  if(!identity) return null;
  if(securityMode()!=="production") return identity;
  const origin=source.get("origin");
  const host=(source.get("x-forwarded-host")??source.get("host")??"").trim();
  const proto=(source.get("x-forwarded-proto")??"https").trim();
  const fetchSite=source.get("sec-fetch-site");
  if(!origin||!host||(fetchSite&&fetchSite!=="same-origin")) return null;
  try {
    const parsed=new URL(origin);
    if(parsed.host!==host||parsed.protocol!==proto+":") return null;
  } catch { return null; }
  return identity;
}
export async function requireRole(required:MacroVisionRole) {
  const identity=authorizeTrustedHeaders(new Headers(await headers()),required);
  if(!identity) throw new Error("Unauthorized MacroVision research operation.");
  return identity;
}
export async function requireMutationRole(required:MacroVisionRole) {
  const identity=authorizeMutationHeaders(new Headers(await headers()),required);
  if(!identity) throw new Error("Unauthorized or cross-origin MacroVision mutation.");
  return identity;
}
