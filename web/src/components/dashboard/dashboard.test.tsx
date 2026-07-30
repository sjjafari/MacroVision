import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { MetricCard } from "@/components/dashboard/metric-card";
import { formatExactDecimal, safeSourceUrl } from "@/lib/dashboard/format";
import { metricFixture, pageFixture } from "@/test/dashboard-fixture";

const setOption = vi.fn();

vi.mock("echarts", () => ({
  init: () => ({
    setOption,
    resize: vi.fn(),
    dispose: vi.fn(),
  }),
}));

describe("dashboard presentation", () => {
  beforeEach(() => {
    setOption.mockClear();
  });

  it("preserves exact Decimal strings without arithmetic", () => {
    expect(formatExactDecimal("1234567890.12345678")).toBe(
      "1٬234٬567٬890.12345678",
    );
    expect(formatExactDecimal("-0.00000000")).toBe("-0.00000000");
  });

  it("renders available values and API comparisons exactly", () => {
    render(<MetricCard definitionLabel="تورم" metric={metricFixture()} />);
    expect(screen.getByLabelText("1234567890.12345678")).toBeInTheDocument();
    expect(screen.getByLabelText("10.00000000")).toBeInTheDocument();
    expect(screen.getByLabelText("0.00000081")).toBeInTheDocument();
    expect(screen.getByText("Federal Reserve Economic Data")).toHaveAttribute(
      "rel",
      "noreferrer noopener",
    );
  });

  it.each([
    ["missing", null, "دادهٔ مفقود"],
    ["stale", "1234567890.12345678", "⚠ دادهٔ قدیمی"],
  ] as const)("renders %s point state without mapping missing to zero", (state, value, label) => {
    render(
      <MetricCard
        definitionLabel="تورم"
        metric={metricFixture({
          state,
          value,
          state_reason: state === "missing" ? "current_observation_missing" : "series_stale",
          freshness: {
            ...metricFixture().freshness,
            status: state === "stale" ? "stale" : "unavailable",
          },
        })}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    if (state === "missing") expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it.each([
    ["missing", "derived_comparison_missing"],
    ["incomparable", "derived_comparison_anchor_mismatch"],
    ["frequency_mismatch", "derived_comparison_frequency_mismatch"],
  ] as const)("keeps current value when comparison is %s", (state, reason) => {
    render(
      <MetricCard
        definitionLabel="تورم"
        metric={metricFixture({
          comparison: {
            ...metricFixture().comparison,
            state,
            state_reason: reason,
          },
        })}
      />,
    );
    expect(screen.getByLabelText("1234567890.12345678")).toBeInTheDocument();
    expect(screen.getByText(state)).toBeInTheDocument();
  });

  it("rejects unsafe source URLs", () => {
    expect(safeSourceUrl("https://user:pass@example.com/path")).toBeNull();
    expect(safeSourceUrl("javascript:alert(1)")).toBeNull();
    expect(safeSourceUrl("https://example.com/path")).toBe("https://example.com/path");
  });

  it("shows a literal API zero but never substitutes zero for missing data", () => {
    const { rerender } = render(
      <MetricCard
        definitionLabel="تورم"
        metric={metricFixture({ value: "0.00000000" })}
      />,
    );
    expect(screen.getByLabelText("0.00000000")).toBeInTheDocument();

    rerender(
      <MetricCard
        definitionLabel="تورم"
        metric={metricFixture({
          state: "missing",
          value: null,
          state_reason: "current_observation_missing",
        })}
      />,
    );
    expect(screen.queryByLabelText("0.00000000")).not.toBeInTheDocument();
  });

  it("renders an accessible dashboard and chart textual fallback", async () => {
    const { container } = render(
      <DashboardPage
        data={pageFixture()}
        eyebrow="داشبورد"
        title="نمای اصلی"
        description="دادهٔ خواندنی"
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("نمای اصلی");
    expect(screen.getByText("جدول متنی داده‌های نمودار")).toBeInTheDocument();
    expect(screen.getByLabelText("missing")).toHaveTextContent("—");
    expect(await axe(container)).toHaveNoViolations();
    await vi.waitFor(() => expect(setOption).toHaveBeenCalledOnce());
    const option = setOption.mock.calls[0][0] as {
      series: { connectNulls: boolean; data: (string | null)[] }[];
    };
    expect(option.series[0].connectNulls).toBe(false);
    expect(option.series[0].data).toEqual([
      "1234567880.12345678",
      null,
    ]);
  });
});
