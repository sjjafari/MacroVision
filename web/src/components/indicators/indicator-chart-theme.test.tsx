import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { buildIndicatorChartOption, IndicatorChart } from "./indicator-chart";
import type { ObservationRead } from "@/lib/indicators/types";

const echarts = vi.hoisted(() => ({ setOption:vi.fn(), resize:vi.fn(), dispose:vi.fn(), fail:false }));
vi.mock("echarts",()=>({init:()=>{if(echarts.fail) throw new Error("private"); return {setOption:echarts.setOption,resize:echarts.resize,dispose:echarts.dispose};}}));

const point: ObservationRead = {id:21,series_id:11,observed_at:"2026-06-01T00:00:00Z",publication_timestamp:null,ingestion_timestamp:"2026-06-02T00:00:00Z",provider_vintage_start:null,provider_vintage_end:null,provider_metadata:{},value:"321.40000000",status:"present",source_reference:null,revision_count:0};
let mutationCallback: MutationCallback | null;
let mediaCallback: ((event:MediaQueryListEvent)=>void) | null;
let mediaRemove: ReturnType<typeof vi.fn>;

function tokens(suffix:string){for(const name of ["text-primary","text-secondary","text-muted","border","border-strong","surface-chart","information"]) document.documentElement.style.setProperty(`--${name}`,`${name}-${suffix}`);}

describe("indicator chart theme integrity",()=>{
  beforeEach(()=>{
    echarts.setOption.mockClear();echarts.resize.mockClear();echarts.dispose.mockClear();echarts.fail=false;
    mutationCallback=null;mediaCallback=null;mediaRemove=vi.fn();document.documentElement.removeAttribute("style");document.documentElement.removeAttribute("data-theme");tokens("dark");
    globalThis.MutationObserver=class{constructor(callback:MutationCallback){mutationCallback=callback;}observe(){}takeRecords(){return [];}disconnect=vi.fn();} as unknown as typeof MutationObserver;
    globalThis.matchMedia=vi.fn((query:string)=>({matches:query.includes("dark"),media:query,onchange:null,addEventListener:(_type:string,callback:EventListener)=>{if(query.includes("color-scheme"))mediaCallback=callback as (event:MediaQueryListEvent)=>void;},removeEventListener:mediaRemove,addListener:vi.fn(),removeListener:vi.fn(),dispatchEvent:vi.fn()})) as unknown as typeof matchMedia;
  });
  it("applies system dark, forced light, and live system theme changes without changing exact text",async()=>{
    const removeResize=vi.spyOn(window,"removeEventListener");
    const {unmount}=render(<IndicatorChart points={[point]} title="تورم"/>);
    expect(screen.getByText("321.40000000")).toBeInTheDocument();
    await vi.waitFor(()=>expect(echarts.setOption).toHaveBeenCalledOnce());
    expect((echarts.setOption.mock.calls[0][0] as ReturnType<typeof buildIndicatorChartOption>).backgroundColor).toBe("surface-chart-dark");
    tokens("light");document.documentElement.dataset.theme="light";mutationCallback?.([],{} as MutationObserver);
    expect((echarts.setOption.mock.calls[1][0] as ReturnType<typeof buildIndicatorChartOption>).series[0].lineStyle.color).toBe("information-light");
    tokens("system");delete document.documentElement.dataset.theme;mediaCallback?.({matches:false} as MediaQueryListEvent);
    expect((echarts.setOption.mock.calls[2][0] as ReturnType<typeof buildIndicatorChartOption>).tooltip.textStyle.color).toBe("text-primary-system");
    expect(screen.getByText("321.40000000")).toBeInTheDocument();
    unmount();expect(mediaRemove).toHaveBeenCalled();expect(removeResize).toHaveBeenCalledWith("resize",expect.any(Function));expect(echarts.dispose).toHaveBeenCalledOnce();removeResize.mockRestore();
  });
  it("contains runtime initialization failures accessibly",async()=>{echarts.fail=true;render(<IndicatorChart points={[point]} title="تورم"/>);expect(await screen.findByRole("alert")).toHaveTextContent("جدول داده همچنان در دسترس است");expect(screen.getByText("321.40000000")).toBeInTheDocument();});
});
