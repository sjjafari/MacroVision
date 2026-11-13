import { afterEach, describe, expect, it } from "vitest";
import { pbkdf2Sync } from "node:crypto";
import { configuredUser, issueSession, verifyPassword, verifySessionToken } from "./session";
import { consumeRateLimit } from "./rate-limit";

const original={...process.env};
afterEach(()=>{process.env={...original};});

describe("public security primitives",()=>{
  it("issues tamper-evident expiring RBAC sessions",()=>{
    process.env.MACROVISION_WEB_SESSION_SECRET="0123456789abcdef0123456789abcdef";
    const {token,session}=issueSession("analyst","operator");
    expect(verifySessionToken(token)).toEqual(session);
    expect(verifySessionToken(token.slice(0,-1)+(token.endsWith("a")?"b":"a"))).toBeNull();
  });
  it("verifies only hardened PBKDF2-SHA256 password hashes",()=>{
    const salt=Buffer.from("macrovision-security-test-salt");
    const hash=pbkdf2Sync("correct horse battery staple",salt,310000,32,"sha256");
    process.env.MACROVISION_WEB_RESEARCH_PASSWORD_HASH=`pbkdf2$sha256$310000$${salt.toString("base64url")}$${hash.toString("base64url")}`;
    process.env.MACROVISION_WEB_RESEARCH_USER="operator";
    expect(configuredUser()).toBe("operator");
    expect(verifyPassword("correct horse battery staple")).toBe(true);
    expect(verifyPassword("wrong")).toBe(false);
    process.env.MACROVISION_WEB_RESEARCH_PASSWORD_HASH=`pbkdf2$sha256$1000$${salt.toString("base64url")}$${hash.toString("base64url")}`;
    expect(verifyPassword("correct horse battery staple")).toBe(false);
  });
  it("fails closed after the configured request budget",()=>{
    const key=`test-${Date.now()}-${Math.random()}`;
    expect(consumeRateLimit(key,2,60000).allowed).toBe(true);
    expect(consumeRateLimit(key,2,60000).allowed).toBe(true);
    const blocked=consumeRateLimit(key,2,60000);
    expect(blocked.allowed).toBe(false);
    expect(blocked.retryAfter).toBeGreaterThan(0);
  });
});
