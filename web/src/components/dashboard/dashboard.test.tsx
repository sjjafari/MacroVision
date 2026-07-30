import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/dashboard-page";
import {
  buildChartOption,
  FeaturedSeriesChart,
  geometryForChartPoint,
  projectExactDecimalForChartGeometry,
  readChartTheme,
} from "@/components/dashboard/featured-series-chart";
import { MetricCard } from "@/components/dashboard/metric-card";
import { formatExactDecimal, safeSourceUrl } from "@/lib/dashboard/format";
import type { ChartPoint, FeaturedChartData } from "@/lib/dashboard/types";
import { metricFixture, pageFixture } from "@/test/dashboard-fixture";

const echarts = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  failInit: false,
}));

vi.mock("echarts", () => ({
  init: () => {
    if (echarts.failInit) throw new Error("private runtime detail");
    return {
      setOption: echarts.setOption,
      resize: echarts.resize,
      dispose: echarts.dispose,
    };
  },
}));

let resizeDisconnect: ReturnType<typeof vi.fn>;
let mutationDisconnect: ReturnType<typeof vi.fn>;
let mutationCallback: MutationCallback | null;
let mediaChange: ((event: MediaQueryListEvent) => void) | null;
let mediaRemove: ReturnType<typeof vi.fn>;

function installObserverMocks() {
  resizeDisconnect = vi.fn();
  mutationDisconnect = vi.fn();
  mutationCallback = null;
  mediaChange = null;
  mediaRemove = vi.fn();
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect = resizeDisconnect;
  } as unknown as typeof ResizeObserver;
  globalThis.MutationObserver = class {
    constructor(callback: MutationCallback) {
      mutationCallback = callback;
    }
    observe() {}
    takeRecords() {
      return [];
    }
    disconnect = mutationDisconnect;
  } as unknown as typeof MutationObserver;
  globalThis.matchMedia = vi.fn(() => ({
    matches: true,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_type: string, callback: EventListener) => {
      mediaChange = callback as (event: MediaQueryListEvent) => void;
    },
    removeEventListener: mediaRemove,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof matchMedia;
}

function setThemeTokens(suffix: string) {
  const root = document.documentElement;
  for (const name of [
    "text-primary",
    "text-secondary",
    "text-muted",
    "border",
    "border-strong",
    "surface-chart",
    "information",
  ]) {
    root.style.setProperty(`--${name}`, `${name}-${suffix}`);
  }
}

function availableChart(
  points?: ChartPoint[],
): Extract<FeaturedChartData, { status: "available" }> {
  const fixture = pageFixture().featuredChart;
  if (fixture.status !== "available") throw new Error("Invalid chart fixture");
  return {
    status: "available",
    metricKey: "headline_cpi",
    title: "شاخص قیمت",
    sourceLabel: "FRED",
    start: "2016-06-01T00:00:00Z",
    end: "2026-06-01T00:00:00Z",
    points: points ?? fixture.points,
  };
}

describe("dashboard presentation", () => {
  beforeEach(() => {
    echarts.setOption.mockClear();
    echarts.resize.mockClear();
    echarts.dispose.mockClear();
    echarts.failInit = false;
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("style");
    installObserverMocks();
    setThemeTokens("dark");
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
    expect(screen.getByText("مقایسه موجود")).toBeInTheDocument();
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
    ["missing", "derived_comparison_missing", "دادهٔ مقایسه مفقود"],
    ["incomparable", "derived_comparison_anchor_mismatch", "مقایسه‌ناپذیر"],
    ["frequency_mismatch", "derived_comparison_frequency_mismatch", "تناوب‌های متفاوت"],
  ] as const)("keeps current value when comparison is %s", (state, reason, label) => {
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
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders complete derived-comparison evidence without fingerprints", () => {
    render(
      <MetricCard
        definitionLabel="تورم"
        metric={metricFixture({
          comparison: {
            ...metricFixture().comparison,
            type: "existing_derived_metric",
            derived_identity: {
              definition_id: 31,
              definition_code: "ANALYTICS.CPI.YOY",
              definition_version: 2,
              run_id: 41,
              observation_id: 51,
            },
            derived_observed_at: "2026-06-01T00:00:00Z",
            derived_calculation_cutoff: "2026-06-10T01:00:00Z",
            derived_completed_at: "2026-06-10T01:01:00Z",
          },
        })}
      />,
    );
    expect(screen.getByText("ANALYTICS.CPI.YOY")).toBeInTheDocument();
    expect(screen.getByText("31 / 2 / 41 / 51")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("fingerprint");
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

  it("projects finite geometry only and preserves inconsistent missing values as gaps", () => {
    expect(projectExactDecimalForChartGeometry("123.45000000")).toBe(123.45);
    expect(projectExactDecimalForChartGeometry("1e9999")).toBeNull();
    expect(
      geometryForChartPoint({
        observedAt: "2026-01-01T00:00:00Z",
        exactValue: "999.00000000",
        status: "missing",
      }),
    ).toBeNull();
  });

  it("uses exact strings in tooltip/table while ECharts receives numbers or gaps", async () => {
    const chart = availableChart([
      {
        observedAt: "2026-05-01T00:00:00Z",
        exactValue: "123.45000000",
        status: "present",
      },
      {
        observedAt: "2026-06-01T00:00:00Z",
        exactValue: "999.00000000",
        status: "missing",
      },
    ]);
    render(<FeaturedSeriesChart chart={chart} />);
    expect(screen.getByLabelText("123.45000000")).toHaveTextContent("123.45000000");
    expect(screen.getByLabelText("missing")).toHaveTextContent("—");
    await vi.waitFor(() => expect(echarts.setOption).toHaveBeenCalledOnce());
    const option = echarts.setOption.mock.calls[0][0] as ReturnType<
      typeof buildChartOption
    >;
    expect(option.series[0].data).toEqual([123.45, null]);
    expect(option.series[0].connectNulls).toBe(false);
    expect(
      option.tooltip.formatter([{ axisValue: "2026-05-01T00:00:00Z" }]),
    ).toContain("123.45000000");
  });

  it("reapplies CSS-token themes for forced-light and system changes", async () => {
    const chart = availableChart();
    const { unmount } = render(<FeaturedSeriesChart chart={chart} />);
    await vi.waitFor(() => expect(echarts.setOption).toHaveBeenCalledOnce());
    expect(
      (echarts.setOption.mock.calls[0][0] as ReturnType<typeof buildChartOption>)
        .backgroundColor,
    ).toBe("surface-chart-dark");

    setThemeTokens("light");
    document.documentElement.dataset.theme = "light";
    mutationCallback?.([], {} as MutationObserver);
    expect(echarts.setOption).toHaveBeenCalledTimes(2);
    expect(
      (echarts.setOption.mock.calls[1][0] as ReturnType<typeof buildChartOption>)
        .backgroundColor,
    ).toBe("surface-chart-light");

    setThemeTokens("system");
    mediaChange?.({ matches: false } as MediaQueryListEvent);
    expect(echarts.setOption).toHaveBeenCalledTimes(3);
    expect(
      (echarts.setOption.mock.calls[2][0] as ReturnType<typeof buildChartOption>)
        .backgroundColor,
    ).toBe("surface-chart-system");

    unmount();
    expect(resizeDisconnect).toHaveBeenCalledOnce();
    expect(mutationDisconnect).toHaveBeenCalledOnce();
    expect(mediaRemove).toHaveBeenCalledOnce();
    expect(echarts.dispose).toHaveBeenCalledOnce();
  });

  it("contains runtime failures and retains exact textual evidence", async () => {
    echarts.failInit = true;
    render(<FeaturedSeriesChart chart={availableChart()} />);
    expect(
      await screen.findByText("نمایش تعاملی نمودار با خطا روبه‌رو شد"),
    ).toBeInTheDocument();
    expect(screen.getByText("جدول متنی داده‌های نمودار")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("private runtime detail");
  });

  it("distinguishes empty and endpoint-error chart states", () => {
    const { rerender } = render(
      <FeaturedSeriesChart
        chart={{ status: "empty", reason: "chart_observations_empty" }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "داده‌ای برای نمودار موجود نیست",
    );
    rerender(
      <FeaturedSeriesChart
        chart={{ status: "error", reason: "chart_read_failed" }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "نمایش تعاملی نمودار با خطا روبه‌رو شد",
    );
  });

  it("reports non-renderable geometry without hiding the exact table", () => {
    render(
      <FeaturedSeriesChart
        chart={availableChart([
          {
            observedAt: "2026-05-01T00:00:00Z",
            exactValue: "1e9999",
            status: "present",
          },
        ])}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "chart_value_not_renderable",
    );
    expect(screen.getByLabelText("1e9999")).toHaveTextContent("1e9999");
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
  });

  it("reads all chart colors from existing CSS design tokens", () => {
    const theme = readChartTheme(document.documentElement);
    const option = buildChartOption(availableChart(), theme);
    expect(option.textStyle.color).toBe("text-primary-dark");
    expect(option.xAxis.axisLine.lineStyle.color).toBe("border-strong-dark");
    expect(option.series[0].lineStyle.color).toBe("information-dark");
  });
});
