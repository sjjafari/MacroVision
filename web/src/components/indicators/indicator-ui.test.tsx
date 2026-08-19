import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import { CatalogPage } from "./catalog-page";
import { projectExactDecimalForChartGeometry } from "./indicator-chart";
import type { IndicatorCatalogPage } from "@/lib/indicators/types";

vi.mock("next/link", () => ({ default: ({ href, children, ...props }: React.ComponentProps<"a">) => <a href={String(href)} {...props}>{children}</a> }));

const data: IndicatorCatalogPage = { limit:12,offset:0,total:2,items:[
  {catalog_order:1,curation_status:"reviewed_private",availability:"available",series_id:11,series_code:"FRED.CPIAUCSL",display_name_fa:"شاخص قیمت مصرف‌کننده",original_name:"Consumer Price Index",description_fa:"شرح دقیق",localized_unit_label:"واحد شاخص",category:"inflation",geography:"US",frequency:"monthly",unit:"index",seasonal_adjustment_status:"seasonally_adjusted",operational_is_active:true,source:{source_id:7,source_code:"FRED",source_name:"FRED",reference_url:"https://fred.stlouisfed.org"},editorial_updated_at:"2026-08-01T00:00:00Z"},
  {catalog_order:2,curation_status:"reviewed_private",availability:"configured_series_missing",series_id:null,series_code:"FRED.MISSING",display_name_fa:"در انتظار اتصال",original_name:null,description_fa:"هنوز متصل نیست",localized_unit_label:null,category:null,geography:null,frequency:null,unit:null,seasonal_adjustment_status:"unknown",operational_is_active:null,source:null,editorial_updated_at:"2026-08-01T00:00:00Z"}
]};

describe("Persian indicator catalog", () => {
  it("renders approved and configured-missing entries without a broken detail link", () => {
    render(<CatalogPage data={data} query={{limit:12,offset:0}}/>);
    expect(screen.getByRole("link",{name:/مشاهدهٔ پژوهش/})).toHaveAttribute("href","/fa/indicators/11");
    expect(screen.getByText("سری هنوز متصل نشده")).toBeInTheDocument();
    expect(screen.queryByRole("link",{name:/در انتظار اتصال/})).not.toBeInTheDocument();
  });
  it("is accessible and exposes labelled filters", async () => {
    const {container}=render(<CatalogPage data={data} query={{search:"تورم",limit:12,offset:0}}/>);
    expect(screen.getByLabelText("جست‌وجو")).toHaveValue("تورم");
    expect(await axe(container)).toHaveNoViolations();
  });
  it("preserves Decimal meaning while geometry projection is explicitly bounded", () => {
    expect(projectExactDecimalForChartGeometry("321.40000000")).toBe(321.4);
    expect(projectExactDecimalForChartGeometry("1e9999")).toBeNull();
    expect(projectExactDecimalForChartGeometry(null)).toBeNull();
  });
});
