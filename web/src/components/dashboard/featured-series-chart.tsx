"use client";

import { useEffect, useRef, useState } from "react";

import type { ChartPoint, FeaturedChartData } from "@/lib/dashboard/types";
import { formatExactDecimal, formatUtcTimestamp } from "@/lib/dashboard/format";

type ChartTheme = {
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  border: string;
  borderStrong: string;
  surface: string;
  brand: string;
};

export function projectExactDecimalForChartGeometry(
  exactValue: string,
): number | null {
  const coordinate = Number(exactValue);
  return Number.isFinite(coordinate) ? coordinate : null;
}

function usableExactValue(point: ChartPoint): string | null {
  return point.status === "present" ? point.exactValue : null;
}

export function geometryForChartPoint(point: ChartPoint): number | null {
  const exact = usableExactValue(point);
  return exact === null ? null : projectExactDecimalForChartGeometry(exact);
}

export function readChartTheme(root: HTMLElement): ChartTheme {
  const styles = getComputedStyle(root);
  const token = (name: string) => styles.getPropertyValue(name).trim();
  return {
    textPrimary: token("--text-primary"),
    textSecondary: token("--text-secondary"),
    textMuted: token("--text-muted"),
    border: token("--border"),
    borderStrong: token("--border-strong"),
    surface: token("--surface-chart"),
    brand: token("--information") || token("--brand"),
  };
}

export function buildChartOption(
  chart: Extract<FeaturedChartData, { status: "available" }>,
  theme: ChartTheme,
) {
  const exactByTimestamp = new Map(
    chart.points.map((point) => [point.observedAt, usableExactValue(point)]),
  );
  return {
    animation: false,
    aria: { enabled: true, description: `نمودار ${chart.title}` },
    backgroundColor: theme.surface,
    textStyle: { color: theme.textPrimary },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.borderStrong,
      textStyle: { color: theme.textPrimary },
      formatter: (raw: unknown) => {
        const params = Array.isArray(raw) ? raw[0] : raw;
        const value = params as { axisValue?: string };
        const timestamp = String(value?.axisValue ?? "");
        const exact = exactByTimestamp.get(timestamp);
        return `${formatUtcTimestamp(timestamp) ?? timestamp}<br/>${
          exact === null || exact === undefined
            ? "دادهٔ مفقود"
            : formatExactDecimal(exact)
        }`;
      },
    },
    xAxis: {
      type: "category",
      data: chart.points.map((point) => point.observedAt),
      axisLabel: { color: theme.textSecondary },
      axisLine: { lineStyle: { color: theme.borderStrong } },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: theme.textSecondary },
      axisLine: { lineStyle: { color: theme.borderStrong } },
      splitLine: { lineStyle: { color: theme.border } },
    },
    series: [
      {
        name: chart.title,
        type: "line",
        showSymbol: true,
        symbol: "circle",
        symbolSize: 7,
        connectNulls: false,
        lineStyle: { color: theme.brand },
        itemStyle: {
          color: theme.brand,
          borderColor: theme.textPrimary,
          borderWidth: 1,
        },
        data: chart.points.map(geometryForChartPoint),
      },
    ],
  };
}

function ChartState({
  kind,
  reason,
}: {
  kind: "empty" | "error";
  reason: string;
}) {
  return (
    <div className={`chart-${kind}-state`} role={kind === "error" ? "alert" : "status"}>
      <strong>
        {kind === "error"
          ? "نمایش تعاملی نمودار با خطا روبه‌رو شد"
          : "داده‌ای برای نمودار موجود نیست"}
      </strong>
      <p>
        {kind === "error"
          ? "کارت‌های داشبورد همچنان معتبرند؛ نمودار را بعداً دوباره بررسی کنید."
          : "در بازهٔ انتخاب‌شده نقطهٔ حاضر و قابل‌نمایشی ثبت نشده است."}
      </p>
      <span className="ltr">{reason}</span>
    </div>
  );
}

export function FeaturedSeriesChart({ chart }: { chart: FeaturedChartData }) {
  const container = useRef<HTMLDivElement>(null);
  const [runtimeFailure, setRuntimeFailure] = useState<{
    chart: FeaturedChartData;
    reason: string;
  } | null>(null);
  const geometryUnavailable =
    chart.status === "available" &&
    !chart.points.some((point) => geometryForChartPoint(point) !== null);
  const runtimeError = geometryUnavailable
    ? "chart_value_not_renderable"
    : runtimeFailure?.chart === chart
      ? runtimeFailure.reason
      : null;

  useEffect(() => {
    if (chart.status !== "available" || !container.current) return;
    if (!chart.points.some((point) => geometryForChartPoint(point) !== null)) {
      return;
    }

    let disposed = false;
    let cleanup = () => {};
    void import("echarts")
      .then((echarts) => {
        if (disposed || !container.current) return;
        const instance = echarts.init(container.current);
        const applyTheme = () => {
          if (!disposed) {
            instance.setOption(
              buildChartOption(chart, readChartTheme(document.documentElement)),
              true,
            );
          }
        };
        applyTheme();

        const resizeObserver = new ResizeObserver(() => instance.resize());
        resizeObserver.observe(container.current);
        const themeObserver = new MutationObserver(applyTheme);
        themeObserver.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ["data-theme"],
        });
        const colorScheme = matchMedia("(prefers-color-scheme: dark)");
        colorScheme.addEventListener("change", applyTheme);
        cleanup = () => {
          resizeObserver.disconnect();
          themeObserver.disconnect();
          colorScheme.removeEventListener("change", applyTheme);
          instance.dispose();
        };
      })
      .catch(() => {
        if (!disposed) {
          setRuntimeFailure({ chart, reason: "chart_runtime_failed" });
        }
      });

    return () => {
      disposed = true;
      cleanup();
    };
  }, [chart]);

  if (chart.status !== "available") {
    return <ChartState kind={chart.status} reason={chart.reason} />;
  }

  return (
    <section className="dashboard-chart" aria-labelledby="featured-chart-title">
      <header>
        <div>
          <p className="eyebrow">نمودار منتخب</p>
          <h2 id="featured-chart-title">{chart.title}</h2>
        </div>
        <p>
          {chart.sourceLabel
            ? `منبع: ${chart.sourceLabel}`
            : "خروجی ماندگاریافته"}
        </p>
      </header>
      {runtimeError && <ChartState kind="error" reason={runtimeError} />}
      <div
        ref={container}
        className="echarts-container"
        role="img"
        aria-label={`نمودار سری زمانی ${chart.title}; مقادیر نمایشی دقیق‌اند و هندسهٔ نمودار ممکن است تقریبی باشد`}
        hidden={runtimeError !== null}
      />
      <details className="chart-table">
        <summary>جدول متنی داده‌های نمودار</summary>
        <div className="chart-table-scroll">
          <table>
            <thead>
              <tr>
                <th>زمان مشاهده</th>
                <th>مقدار دقیق</th>
              </tr>
            </thead>
            <tbody>
              {chart.points.map((point) => {
                const exact = usableExactValue(point);
                return (
                  <tr key={point.observedAt}>
                    <td>
                      <time dateTime={point.observedAt}>
                        {formatUtcTimestamp(point.observedAt)}
                      </time>
                    </td>
                    <td className="ltr" aria-label={exact ?? "missing"}>
                      {exact === null ? "—" : formatExactDecimal(exact)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
      <p className="chart-range">
        بازهٔ انتخاب‌شده: <span className="ltr">{chart.start}</span> تا{" "}
        <span className="ltr">{chart.end}</span>
      </p>
      <p className="chart-geometry-note">
        مختصات نمودار فقط برای هندسه به عدد محدود تبدیل می‌شوند؛ همهٔ متن‌ها و
        شواهد مقدار دقیق API را حفظ می‌کنند.
      </p>
    </section>
  );
}
