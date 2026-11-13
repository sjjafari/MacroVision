import { afterEach, describe, expect, it } from "vitest";
import { authorizeMutationHeaders, authorizeTrustedHeaders } from "./request-auth";

const original={...process.env};
afterEach(()=>{process.env={...original};});

describe("trusted ingress RBAC",()=>{
  it("fails closed in production without trusted proxy proof",()=>{
    process.env.MACROVISION_SECURITY_MODE="production";
    process.env.MACROVISION_TRUSTED_PROXY_SECRET="x".repeat(32);
    process.env.MACROVISION_OPERATOR_USERS="sjjafari";
    expect(authorizeTrustedHeaders(new Headers({"x-auth-request-user":"sjjafari"}),"reader")).toBeNull();
  });
  it("enforces role ordering only after trusted proxy proof",()=>{
    process.env.MACROVISION_SECURITY_MODE="production";
    process.env.MACROVISION_TRUSTED_PROXY_SECRET="s".repeat(32);
    process.env.MACROVISION_OPERATOR_USERS="sjjafari";
    process.env.MACROVISION_READER_USERS="reader";
    const operator=new Headers({"x-auth-request-user":"sjjafari","x-macrovision-proxy-secret":"s".repeat(32)});
    const reader=new Headers({"x-auth-request-user":"reader","x-macrovision-proxy-secret":"s".repeat(32)});
    expect(authorizeTrustedHeaders(operator,"research")?.role).toBe("operator");
    expect(authorizeTrustedHeaders(reader,"reader")?.role).toBe("reader");
    expect(authorizeTrustedHeaders(reader,"research")).toBeNull();
  });

  it("requires same-origin proof for production mutations",()=>{
    process.env.MACROVISION_SECURITY_MODE="production";
    process.env.MACROVISION_TRUSTED_PROXY_SECRET="s".repeat(32);
    process.env.MACROVISION_RESEARCH_USERS="analyst";
    const base={"x-auth-request-user":"analyst","x-macrovision-proxy-secret":"s".repeat(32),"host":"macrovision.example","x-forwarded-proto":"https"};
    expect(authorizeMutationHeaders(new Headers({...base,origin:"https://macrovision.example","sec-fetch-site":"same-origin"}),"research")?.role).toBe("research");
    expect(authorizeMutationHeaders(new Headers({...base,origin:"https://attacker.example","sec-fetch-site":"cross-site"}),"research")).toBeNull();
    expect(authorizeMutationHeaders(new Headers(base),"research")).toBeNull();
  });
  it("keeps deterministic local preview available for smoke and offline work",()=>{
    process.env.MACROVISION_SECURITY_MODE="private_preview";
    expect(authorizeTrustedHeaders(new Headers(),"operator")).toEqual({user:"local-preview",role:"operator"});
  });
});
