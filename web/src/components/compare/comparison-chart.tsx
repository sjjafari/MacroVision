"use client";

import { useEffect, useRef, useState } from "react";
import { readChartTheme } from "@/components/dashboard/featured-series-chart";
import type { ComparisonRead } from "@/lib/compare/types";

export function projectComparisonDecimal(value: string | null) {
  if (value === null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

const lineTypes = ["solid", "dashed", "dotted", "solid"] as const;
const symbols = ["circle", "rect", "triangle", "diamond"] as const;

export function buildComparisonOption(data: ComparisonRead) {
  const theme = readChartTheme(document.documentElement);
  const axes = Array.from(new Set(data.series.map(item => item.axis_id)));
  const axisIndex = new Map(axes.map((axis, index) => [axis, index]));
  const exact = new Map<string,string>();
  for (const series of data.series) for (const point of series.points) {
    if (point.value !== null) exact.set(`${series.kind}:${series.resource_id}:${point.observed_at}`, point.value);
  }
  return {
    animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
    backgroundColor: theme.surface,
    textStyle: { color: theme.textPrimary },
    grid: { left: 70, right: axes.length > 1 ? 70 : 24, top: 45, bottom: 55 },
    legend: { textStyle: { color: theme.textSecondary } },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.borderStrong,
      textStyle: { color: theme.textPrimary },
      formatter: (raw: unknown) => {
        const items = Array.isArray(raw) ? raw as Array<{seriesIndex:number;data?:unknown[];axisValue?:string}> : [];
        const timestamp = String(items[0]?.axisValue ?? "");
        const rows = items.map(item => {
          const series = data.series[item.seriesIndex];
          const value = exact.get(`${series.kind}:${series.resource_id}:${timestamp}`) ?? "دادهٔ مفقود";
          return `${series.title}: ${value}`;
        });
        return [timestamp, ...rows].join("<br>");
      },
    },
    xAxis: { type: "time", axisLabel: { color: theme.textSecondary }, axisLine: { lineStyle: { color: theme.borderStrong } } },
    yAxis: axes.map((axis, index) => {
      const sample = data.series.find(item => item.axis_id === axis);
      return {
        type: "value", scale: true, name: `${sample?.unit ?? ""}${sample?.currency ? ` · ${sample.currency}` : ""}`,
        position: index % 2 === 0 ? "left" : "right",
        offset: index > 1 ? (index - 1) * 45 : 0,
        axisLabel: { color: theme.textSecondary }, nameTextStyle: { color: theme.textSecondary },
        axisLine: { show: true, lineStyle: { color: theme.borderStrong } },
        splitLine: { show: index === 0, lineStyle: { color: theme.border } },
      };
    }),
    series: data.series.map((series, index) => ({
      name: series.title, type: "line", yAxisIndex: axisIndex.get(series.axis_id) ?? 0,
      showSymbol: true, symbol: symbols[index], symbolSize: 6, connectNulls: false,
      lineStyle: { color: theme.brand, type: lineTypes[index], width: index === 0 ? 3 : 2 },
      itemStyle: { color: theme.brand },
      data: series.points.map(point => [point.observed_at, point.status === "present" ? projectComparisonDecimal(point.value) : null]),
    })),
  };
}

export function ComparisonChart({ data }: { data: ComparisonRead }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error,setError] = useState(false);
  useEffect(() => {
    let disposed=false; let cleanup=()=>{};
    void import("echarts").then(echarts => {
      if(disposed || !ref.current) return;
      const instance=echarts.init(ref.current);
      const apply=()=>{ if(!disposed) instance.setOption(buildComparisonOption(data),true); };
      const resize=()=>instance.resize(); apply(); window.addEventListener("resize",resize);
      const observer=new MutationObserver(apply); observer.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
      const media=matchMedia("(prefers-color-scheme: dark)"); media.addEventListener("change",apply);
      cleanup=()=>{window.removeEventListener("resize",resize);observer.disconnect();media.removeEventListener("change",apply);instance.dispose();};
    }).catch(()=>{if(!disposed)setError(true);});
    return()=>{disposed=true;cleanup();};
  },[data]);
  return <section className="dashboard-chart compare-chart" aria-labelledby="compare-chart-title">
    <header><div><h2 id="compare-chart-title">نمودار مقایسه</h2><p>هر سری روی زمان واقعی خودش رسم می‌شود؛ هیچ هم‌ترازی، پرکردن یا تبدیل دوره‌ای در مرورگر انجام نمی‌شود.</p></div></header>
    {error ? <div className="chart-error-state" role="alert">نمودار در دسترس نیست؛ جدول دقیق داده‌ها پایین صفحه باقی می‌ماند.</div> : <div ref={ref} className="echarts-container" role="img" aria-label="نمودار مقایسه شاخص‌ها" />}
  </section>;
}
