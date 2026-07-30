import { describe, expect, it, vi } from "vitest";

import { chartWindow, loadDashboardPage } from "@/lib/dashboard/loader";
import type { DashboardReadTransport } from "@/lib/dashboard/server-transport";
import type {
  DashboardDefinition,
  DashboardSummary,
  ObservationRead,
} from "@/lib/dashboard/types";
import {
  dashboardDefinition,
  summaryFixture,
} from "@/test/dashboard-fixture";

function transportFixture(): DashboardReadTransport {
  return {
    definition: vi.fn(async () => ({ data: dashboardDefinition, status: 200 })),
    summary: vi.fn(async () => ({ data: summaryFixture(), status: 200 })),
    rawObservations: vi.fn(async () => ({
      status: 200,
      data: [
        {
          id: 1,
          series_id: 11,
          observed_at: "2026-06-01T00:00:00Z",
          publication_timestamp: null,
          ingestion_timestamp: "2026-06-01T01:00:00Z",
          provider_vintage_start: null,
          provider_vintage_end: null,
          provider_metadata: {},
          value: "1234567890.12345678",
          status: "present",
          source_reference: null,
          revision_count: 0,
        } satisfies ObservationRead,
      ],
    })),
    derivedObservations: vi.fn(async () => ({
      status: 200,
      data: {
        definition_id: 1,
        definition_version: 1,
        run_id: 1,
        limit: 200,
        offset: 0,
        items: [],
      },
    })),
  };
}

describe("dashboard server loader", () => {
  it("uses two bounded parallel page reads and one featured chart read", async () => {
    const transport = transportFixture();
    const result = await loadDashboardPage("home", transport);
    expect(result.status).toBe("ready");
    expect(transport.definition).toHaveBeenCalledOnce();
    expect(transport.summary).toHaveBeenCalledOnce();
    expect(transport.rawObservations).toHaveBeenCalledWith(
      11,
      "2016-06-01T00:00:00.000Z",
      "2026-06-01T00:00:00.000Z",
    );
    expect(transport.derivedObservations).not.toHaveBeenCalled();
  });

  it("rejects invalid codes and inconsistent contracts without fan-out", async () => {
    const transport = transportFixture();
    expect(await loadDashboardPage("unknown", transport)).toEqual({
      status: "error",
      code: "invalid_dashboard",
    });
    expect(transport.definition).not.toHaveBeenCalled();

    transport.summary = vi.fn(async () => ({
      data: { ...summaryFixture(), dashboard_code: "macro" as const },
      status: 200,
    }));
    expect(await loadDashboardPage("home", transport)).toEqual({
      status: "error",
      code: "invalid_contract",
    });
    expect(transport.rawObservations).not.toHaveBeenCalled();
  });

  it("returns safe page and chart errors without exposing exceptions", async () => {
    const unavailable = transportFixture();
    unavailable.definition = vi.fn(async () => {
      throw new Error("http://secret-backend:9999/internal traceback");
    });
    expect(await loadDashboardPage("home", unavailable)).toEqual({
      status: "error",
      code: "unavailable",
    });

    const chartFailure = transportFixture();
    chartFailure.rawObservations = vi.fn(async () => {
      throw new Error("provider must not be shown");
    });
    const result = await loadDashboardPage("home", chartFailure);
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.featuredChart).toEqual({
        status: "error",
        reason: "chart_read_failed",
      });
    }
  });

  it("maps missing dashboards and upstream failures to stable page errors", async () => {
    const missing = transportFixture();
    missing.definition = vi.fn(async () => ({ data: null, status: 404 }));
    expect(await loadDashboardPage("home", missing)).toEqual({
      status: "error",
      code: "not_found",
    });

    const badGateway = transportFixture();
    badGateway.summary = vi.fn(async () => ({ data: null, status: 502 }));
    expect(await loadDashboardPage("home", badGateway)).toEqual({
      status: "error",
      code: "unavailable",
    });

    const timeout = transportFixture();
    timeout.definition = vi.fn(async () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    expect(await loadDashboardPage("home", timeout)).toEqual({
      status: "error",
      code: "unavailable",
    });
  });

  it("uses the bounded derived observation path for a derived featured metric", async () => {
    const transport = transportFixture();
    const definition: DashboardDefinition = structuredClone(dashboardDefinition);
    definition.groups[0].metrics[0] = {
      ...definition.groups[0].metrics[0],
      kind: "derived",
      raw_series_code: null,
      derived_definition_code: "ANALYTICS.CPI.YOY",
    };
    const summary: DashboardSummary = summaryFixture();
    summary.groups[0].metrics[0] = {
      ...summary.groups[0].metrics[0],
      kind: "derived",
      raw_identity: null,
      derived_identity: {
        definition_id: 31,
        definition_code: "ANALYTICS.CPI.YOY",
        definition_version: 2,
        run_id: 41,
        observation_id: 51,
      },
    };
    transport.definition = vi.fn(async () => ({ data: definition, status: 200 }));
    transport.summary = vi.fn(async () => ({ data: summary, status: 200 }));

    const result = await loadDashboardPage("home", transport);

    expect(result.status).toBe("ready");
    expect(transport.derivedObservations).toHaveBeenCalledWith(
      31,
      "2016-06-01T00:00:00.000Z",
      "2026-06-01T00:00:00.000Z",
    );
    expect(transport.rawObservations).not.toHaveBeenCalled();
  });

  it("uses deterministic frequency windows and rejects irregular charts", () => {
    expect(chartWindow("daily", "2026-06-01T00:00:00Z")?.end).toBe(
      "2026-06-01T00:00:00.000Z",
    );
    expect(chartWindow("monthly", "2026-06-01T00:00:00Z")?.start).toBe(
      "2016-06-01T00:00:00.000Z",
    );
    expect(chartWindow("quarterly", "2026-06-01T00:00:00Z")?.start).toBe(
      "1996-06-01T00:00:00.000Z",
    );
    expect(chartWindow("annual", "2026-06-01T00:00:00Z")?.start).toBe(
      "1926-06-01T00:00:00.000Z",
    );
    expect(chartWindow("irregular", "2026-06-01T00:00:00Z")).toBeNull();
  });
});
