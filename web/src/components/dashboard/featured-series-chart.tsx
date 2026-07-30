"use client";

import { useEffect, useRef } from "react";

import type { FeaturedChartData } from "@/lib/dashboard/types";
import { formatExactDecimal, formatUtcTimestamp } from "@/lib/dashboard/format";

export function FeaturedSeriesChart({ chart }: { chart: FeaturedChartData }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chart.status !== "available" || !container.current) return;
    let disposed = false;
    let cleanup = () => {};
    void import("echarts").then((echarts) => {
      if (disposed || !container.current) return;
      const instance = echarts.init(container.current);
      const exactByTimestamp = new Map(
        chart.points.map((point) => [point.observedAt, point.exactValue]),
      );
      instance.setOption({
        animation: false,
        aria: { enabled: true, description: `نمودار ${chart.title}` },
        tooltip: {
          trigger: "axis",
          formatter: (raw: unknown) => {
            const params = Array.isArray(raw) ? raw[0] : raw;
            const value = params as { axisValue?: string };
            const timestamp = String(value?.axisValue ?? "");
            const exact = exactByTimestamp.get(timestamp);
            return `${formatUtcTimestamp(timestamp) ?? timestamp}<br/>${
              exact === null || exact === undefined ? "دادهٔ مفقود" : formatExactDecimal(exact)
            }`;
          },
        },
        xAxis: { type: "category", data: chart.points.map((point) => point.observedAt) },
        yAxis: { type: "value", scale: true },
        series: [
          {
            name: chart.title,
            type: "line",
            showSymbol: true,
            symbol: "circle",
            symbolSize: 7,
            connectNulls: false,
            data: chart.points.map((point) => point.exactValue),
          },
        ],
      });
      const observer = new ResizeObserver(() => instance.resize());
      observer.observe(container.current);
      cleanup = () => {
        observer.disconnect();
        instance.dispose();
      };
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [chart]);

  if (chart.status !== "available") {
    return (
      <div className="chart-empty-state" role="status">
        <strong>نمودار در دسترس نیست</strong>
        <p>دادهٔ ماندگاریافته و قابل‌استفاده برای این نمودار موجود نیست.</p>
      </div>
    );
  }

  return (
    <section className="dashboard-chart" aria-labelledby="featured-chart-title">
      <header>
        <div>
          <p className="eyebrow">نمودار منتخب</p>
          <h2 id="featured-chart-title">{chart.title}</h2>
        </div>
        <p>{chart.sourceLabel ? `منبع: ${chart.sourceLabel}` : "خروجی ماندگاریافته"}</p>
      </header>
      <div
        ref={container}
        className="echarts-container"
        role="img"
        aria-label={`نمودار سری زمانی ${chart.title}; نقاط مفقود به‌صورت شکاف نمایش داده می‌شوند`}
      />
      <details className="chart-table">
        <summary>جدول متنی داده‌های نمودار</summary>
        <div className="chart-table-scroll">
          <table>
            <thead><tr><th>زمان مشاهده</th><th>مقدار دقیق</th></tr></thead>
            <tbody>
              {chart.points.map((point) => (
                <tr key={point.observedAt}>
                  <td><time dateTime={point.observedAt}>{formatUtcTimestamp(point.observedAt)}</time></td>
                  <td className="ltr" aria-label={point.exactValue ?? "missing"}>
                    {point.exactValue === null ? "—" : formatExactDecimal(point.exactValue)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="chart-range">
        بازهٔ انتخاب‌شده: <span className="ltr">{chart.start}</span> تا{" "}
        <span className="ltr">{chart.end}</span>
      </p>
    </section>
  );
}
