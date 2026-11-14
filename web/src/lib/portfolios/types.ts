import type { components } from "@/lib/api/generated/schema";
export type Portfolio=components["schemas"]["PortfolioRead"];
export type PortfolioSummary=components["schemas"]["PortfolioSummary"];
export type Transaction=components["schemas"]["TransactionRead"];
export type Snapshot=components["schemas"]["SnapshotRead"];
export const TRANSACTION_FA:Record<components["schemas"]["TransactionType"],string>={buy:"خرید ثبت‌شده",sell:"فروش ثبت‌شده",deposit:"واریز",withdrawal:"برداشت",fee:"کارمزد",dividend:"سود نقدی",interest:"بهره"};
