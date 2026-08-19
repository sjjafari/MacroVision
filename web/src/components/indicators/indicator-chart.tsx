"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { readChartTheme } from "@/components/dashboard/featured-series-chart";
import type { ObservationRead } from "@/lib/indicators/types";
import { faDate } from "./labels";

export function projectExactDecimalForChartGeometry(value: string | null) {
  if (value === null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function buildIndicatorChartOption(points: ObservationRead[]) {
  const theme = readChartTheme(document.documentElement);
  const projected = points.map((point) => [
    point.observed_at,
    point.status === "present"
      ? projectExactDecimalForChartGeometry(point.value)
      : null,
  ]);
  return {
    animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
    backgroundColor: theme.surface,
    textStyle: { color: theme.textPrimary },
    grid: { left: 55, right: 20, top: 25, bottom: 45 },
    xAxis: {
      type: "time",
      axisLabel: { color: theme.textSecondary },
      axisLine: { lineStyle: { color: theme.borderStrong } },
      splitLine: { lineStyle: { color: theme.border } },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: theme.textSecondary },
      axisLine: { lineStyle: { color: theme.borderStrong } },
      splitLine: { lineStyle: { color: theme.border } },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.borderStrong,
      textStyle: { color: theme.textPrimary },
      formatter: (items: unknown) => {
        const first = (items as Array<{ dataIndex: number }>)[0];
        const point = points[first?.dataIndex ?? 0];
        return `${point?.observed_at ?? ""}<br>${point?.value ?? "—"}`;
      },
    },
    series: [
      {
        type: "line",
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: theme.brand },
        itemStyle: { color: theme.brand },
        data: projected,
      },
    ],
  };
}

export function IndicatorChart({ points, title }: { points: ObservationRead[]; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  const stablePoints = useMemo(() => points, [points]);

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};
    void import("echarts")
      .then((echarts) => {
        if (disposed || !ref.current) return;
        const instance = echarts.init(ref.current);
        const applyTheme = () => {
          if (!disposed) instance.setOption(buildIndicatorChartOption(stablePoints), true);
        };
        const onResize = () => instance.resize();
        applyTheme();
        window.addEventListener("resize", onResize);
        const themeObserver = new MutationObserver(applyTheme);
        themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
        const colorScheme = matchMedia("(prefers-color-scheme: dark)");
        colorScheme.addEventListener("change", applyTheme);
        cleanup = () => {
          window.removeEventListener("resize", onResize);
          themeObserver.disconnect();
          colorScheme.removeEventListener("change", applyTheme);
          instance.dispose();
        };
      })
      .catch(() => {
        if (!disposed) setError(true);
      });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [stablePoints]);

  return <section className="dashboard-chart" aria-labelledby="indicator-chart-title"><header><div><h2 id="indicator-chart-title">تاریخچهٔ {title}</h2><p>تبدیل عدد فقط برای هندسهٔ نمودار است؛ متن دقیق از API حفظ می‌شود.</p></div></header>{error ? <div className="chart-error-state" role="alert">نمایش نمودار ممکن نیست؛ جدول داده همچنان در دسترس است.</div> : <div ref={ref} className="echarts-container" role="img" aria-label={`نمودار تاریخی ${title}`} />}
    <details className="chart-table"><summary>جدول دسترس‌پذیر داده‌ها</summary><div className="chart-table-scroll"><table><thead><tr><th>زمان مشاهده</th><th>مقدار دقیق</th><th>وضعیت</th></tr></thead><tbody>{points.map(p=><tr key={p.id}><td>{faDate(p.observed_at)}</td><td dir="ltr">{p.value ?? "—"}</td><td>{p.status === "present" ? "موجود" : "مفقود"}</td></tr>)}</tbody></table></div></details></section>;
}
