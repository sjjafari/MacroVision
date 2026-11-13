import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import { CatalogPage } from "./catalog-page";
import { IndicatorDetailPage } from "./detail-page";
import { projectExactDecimalForChartGeometry } from "./indicator-chart";
import { relatedReasonLabel } from "./labels";
import type { IndicatorCatalogPage, IndicatorDetailData } from "@/lib/indicators/types";

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

  it("renders an explicit historical cutoff boundary without current derived evidence", () => {
    const historical = { detail:{curation:{curation_status:"reviewed_private",catalog_order:1,editorial_updated_at:"2026-06-01T00:00:00Z",private_preview:true,public_eligibility:false},presentation:{display_name_fa:"تورم",original_name:"CPI",description_fa:"شرح",methodology_summary_fa:"روش",localized_unit_label:"درصد",source_attribution_fa:"FRED",seasonal_adjustment_status:"seasonally_adjusted",source_methodology_url:null},canonical:{series_id:11,series_code:"FRED.CPI",name:"CPI",description:"Canonical",category:"inflation",geography:"US",frequency:"monthly",unit:"index",currency:null,is_active:true,stale_after_days:30,created_at:"2026-01-01T00:00:00Z",updated_at:"2026-06-01T00:00:00Z"},source:{source_id:7,source_code:"FRED",source_name:"FRED",reference_url:null,description:"source"}}, snapshot:{mode:"historical_as_of",requested_as_of:"2026-06-30T23:59:59.999Z",generated_at:"2026-07-01T00:00:00Z",state:"available",state_reason:null,value:"321.40000000",observation_identity:{series_id:11,observation_id:21,revision_count:1},observed_at:"2026-06-01T00:00:00Z",source_publication_timestamp:null,knowledge_cutoff:"2026-06-30T23:59:59.999Z",unit:"index",localized_unit_label:"درصد",frequency:"monthly",geography:"US",source:{source_id:7,source_code:"FRED",source_name:"FRED",reference_url:null},source_attribution_fa:"FRED",freshness:{evaluated_at:"2026-06-30T23:59:59.999Z",policy:"raw_series_stale_after_days",stale_after_days:30,age_basis:"observed_at",status:"current"},comparison:{type:"previous_observation",basis_code:"previous",basis_label_fa:"قبلی",anchor_policy:"previous_observation",state:"available",state_reason:null,absolute_change:"1.30000000",percentage_change:"0.40000000",reference_value:"320.10000000"}},chart:{status:"empty",points:[]},revisions:[],relatedSection:{status:"historical_not_supported"},asOf:"2026-06-30T23:59:59.999Z" } as unknown as IndicatorDetailData;
    render(<IndicatorDetailPage data={historical}/>);
    expect(screen.getByText("2026-06-30T23:59:59.999Z")).toBeInTheDocument();
    expect(screen.getByText(/شاخص‌های مشتق و Lineage در نمای تاریخی/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("3.25000000");
    expect(document.body.textContent).not.toContain("41 / 51");
  });

  it("localizes known and unknown technical missing reasons", () => {
    expect(relatedReasonLabel("definition_source_mismatch")).toBe("منبع نتیجه با شاخص بازبینی‌شده یکسان نیست.");
    expect(relatedReasonLabel("private_unknown_code")).toBe("دلیل در دسترس نبودن نتیجه به‌صورت امن ثبت شده است.");
  });
});
