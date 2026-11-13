import { afterEach, describe, expect, it } from "vitest";
import { authorizeTrustedHeaders } from "./request-auth";

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
  it("keeps deterministic local preview available for smoke and offline work",()=>{
    process.env.MACROVISION_SECURITY_MODE="private_preview";
    expect(authorizeTrustedHeaders(new Headers(),"operator")).toEqual({user:"local-preview",role:"operator"});
  });
});
