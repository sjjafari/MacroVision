import { render,screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe,expect,it,vi } from "vitest";
import { DecisionIndex } from "./decision-index";
import { DecisionDetail } from "./decision-detail";
import type { DecisionCase,DecisionRevision } from "@/lib/decisions/types";
vi.mock("@/lib/decisions/actions",()=>({createDecisionAction:vi.fn(),addHypothesisAction:vi.fn(),addEvidenceAction:vi.fn(),addCriticAction:vi.fn(),addInvalidationRuleAction:vi.fn(),reviseDecisionAction:vi.fn(),activateDecisionAction:vi.fn(),invalidateDecisionAction:vi.fn(),closeDecisionAction:vi.fn()}));
vi.mock("next/link",()=>({default:({href,children,...props}:React.ComponentProps<"a">)=><a href={String(href)} {...props}>{children}</a>}));
const d:DecisionCase={id:7,title:"تز تورم",question:"آیا تورم پایدار می‌ماند؟",context:"زمینه",rationale:"منطق",probability:"0.650000",confidence:"0.700000",status:"under_review",current_version:2,created_at:"2026-01-01T00:00:00Z",updated_at:"2026-02-01T00:00:00Z",hypotheses:[{id:1,decision_id:7,statement:"تورم چسبنده است",rationale:"",created_at:"2026-01-01T00:00:00Z"}],supporting_evidence:[],opposing_evidence:[],critic_reviews:[],invalidation_rules:[],outcome:null};
const h:DecisionRevision[]=[{id:1,decision_id:7,version:1,event:"created",status:"draft",probability:"0.600000",confidence:"0.500000",rationale:"اولیه",change_summary:"ایجاد",created_at:"2026-01-01T00:00:00Z"}];
describe("Decision Intelligence reader",()=>{
 it("keeps exact scores and balanced evidence gaps",async()=>{const {container}=render(<DecisionDetail decision={d} history={h}/>);expect(screen.getByText("0.650000")).toBeInTheDocument();expect(screen.getByText("عملیات ثبت‌شونده")).toBeInTheDocument();expect(screen.getByText("شاهد موافق ثبت نشده است.")).toBeInTheDocument();expect(screen.getByText("شاهد مخالف ثبت نشده است.")).toBeInTheDocument();expect(await axe(container)).toHaveNoViolations();});
 it("links index cards to protected dossiers",()=>{render(<DecisionIndex decisions={[d]}/>);expect(screen.getByRole("link",{name:"مشاهده پرونده"})).toHaveAttribute("href","/fa/decisions/7");expect(screen.getByText("ایجاد پرونده تصمیم جدید")).toBeInTheDocument();});
});
