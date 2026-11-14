import type { components } from "@/lib/api/generated/schema";

export type DecisionCase = components["schemas"]["DecisionCaseRead"];
export type DecisionRevision = components["schemas"]["DecisionRevisionRead"];
export type DecisionStatus = components["schemas"]["DecisionStatus"];

export const DECISION_STATUS_FA: Record<DecisionStatus,string> = {
  draft:"پیش‌نویس", under_review:"در حال بررسی", active:"فعال", invalidated:"باطل‌شده", closed:"بسته‌شده"
};

export function decisionCompleteness(decision: DecisionCase) {
  return [
    { key:"hypothesis", label:"فرضیه", complete:decision.hypotheses.length>0 },
    { key:"supporting", label:"شواهد موافق", complete:decision.supporting_evidence.length>0 },
    { key:"opposing", label:"شواهد مخالف", complete:decision.opposing_evidence.length>0 },
    { key:"critic", label:"نقد مستقل", complete:decision.critic_reviews.length>0 },
    { key:"invalidation", label:"شرط ابطال", complete:decision.invalidation_rules.length>0 },
  ] as const;
}
