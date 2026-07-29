import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const snapshotText = readFileSync(
  resolve(process.cwd(), "openapi", "macrovision.openapi.json"),
  "utf8",
);
const snapshot = JSON.parse(snapshotText) as {
  info: { version: string };
  paths: Record<string, unknown>;
};
const proxySource = readFileSync(
  resolve(process.cwd(), "src", "app", "api", "v1", "[...path]", "route.ts"),
  "utf8",
);
const environmentExample = readFileSync(resolve(process.cwd(), ".env.example"), "utf8");

describe("generated API contract", () => {
  it("pins the backend OpenAPI version and required routes", () => {
    expect(snapshot.info.version).toBe("0.7.0");
    expect(snapshot.paths).toHaveProperty("/api/v1/data-series");
    expect(snapshot.paths).toHaveProperty(
      "/api/v1/derived-series/{definition_id}/observations/latest",
    );
    expect(snapshot.paths).toHaveProperty("/api/v1/analytics-runs/{run_id}");
  });

  it("does not expose private Analytics fingerprints", () => {
    for (const field of [
      "request_fingerprint",
      "snapshot_fingerprint",
      "reusable_fingerprint",
      "parameters_fingerprint",
    ]) {
      expect(snapshotText).not.toContain(field);
    }
  });

  it("keeps the backend URL server-only", () => {
    expect(environmentExample).toContain("MACROVISION_BACKEND_URL=");
    expect(environmentExample).not.toContain("NEXT_PUBLIC_");
  });

  it("does not convert proxied Decimal strings to Number", () => {
    expect(proxySource).not.toMatch(/\bNumber\s*\(/);
    const exactDecimal = "1234567890.12345678";
    expect(JSON.parse(JSON.stringify({ value: exactDecimal })).value).toBe(exactDecimal);
  });
});
