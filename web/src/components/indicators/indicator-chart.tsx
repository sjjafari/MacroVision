"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ObservationRead } from "@/lib/indicators/types";
import { faDate } from "./labels";

export function projectExactDecimalForChartGeometry(value: string | null) { if (value === null) return null; const number = Number(value); return Number.isFinite(number) ? number : null; }
export function IndicatorChart({ points, title }: { points: ObservationRead[]; title: string }) {
  const ref = useRef<HTMLDivElement>(null); const [error, setError] = useState(false);
  const projected = useMemo(() => points.map(p => [p.observed_at, p.status === "present" ? projectExactDecimalForChartGeometry(p.value) : null]), [points]);
  useEffect(() => { let instance: { dispose(): void; resize(): void; setOption(option: unknown): void } | undefined; let active = true; const onResize = () => instance?.resize();
    void import("echarts").then(e => { if (!active || !ref.current) return; instance=e.init(ref.current); instance.setOption({ animation: !matchMedia("(prefers-reduced-motion: reduce)").matches, grid:{left:55,right:20,top:25,bottom:45}, xAxis:{type:"time"}, yAxis:{type:"value",scale:true}, tooltip:{trigger:"axis",formatter:(items: unknown)=>{const first=(items as Array<{dataIndex:number}>)[0]; const point=points[first?.dataIndex ?? 0]; return `${point?.observed_at ?? ""}<br>${point?.value ?? "—"}`;}}, series:[{type:"line",showSymbol:false,connectNulls:false,data:projected}] }); window.addEventListener("resize",onResize); }).catch(()=>active&&setError(true)); return()=>{active=false;window.removeEventListener("resize",onResize);instance?.dispose();}; },[points,projected]);
  return <section className="dashboard-chart" aria-labelledby="indicator-chart-title"><header><div><h2 id="indicator-chart-title">تاریخچهٔ {title}</h2><p>تبدیل عدد فقط برای هندسهٔ نمودار است؛ متن دقیق از API حفظ می‌شود.</p></div></header>{error ? <div className="chart-error-state" role="alert">نمایش نمودار ممکن نیست؛ جدول داده همچنان در دسترس است.</div> : <div ref={ref} className="echarts-container" role="img" aria-label={`نمودار تاریخی ${title}`} />}
    <details className="chart-table"><summary>جدول دسترس‌پذیر داده‌ها</summary><div className="chart-table-scroll"><table><thead><tr><th>زمان مشاهده</th><th>مقدار دقیق</th><th>وضعیت</th></tr></thead><tbody>{points.map(p=><tr key={p.id}><td>{faDate(p.observed_at)}</td><td dir="ltr">{p.value ?? "—"}</td><td>{p.status === "present" ? "موجود" : "مفقود"}</td></tr>)}</tbody></table></div></details></section>;
}
