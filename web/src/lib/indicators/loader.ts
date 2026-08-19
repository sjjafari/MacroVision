import "server-only";

import { createIndicatorTransport, type IndicatorTransport } from "@/lib/indicators/server-transport";
import type { DataRevisionRead, IndicatorDetailResult, IndicatorQuery, RelatedSection } from "@/lib/indicators/types";

const allowedCategories = new Set(["inflation", "employment", "growth", "interest_rate", "currency", "commodity", "equity_index", "volatility", "liquidity", "custom"]);
const allowedFrequencies = new Set(["daily", "weekly", "monthly", "quarterly", "annual", "irregular"]);

function bounded(value: string | undefined, max = 120) { const v = value?.trim(); return v && v.length <= max ? v : undefined; }
export function normalizeCatalogQuery(params: Record<string, string | string[] | undefined>): IndicatorQuery {
  const one = (key: string) => typeof params[key] === "string" ? params[key] as string : undefined;
  const limit = 12;
  const page = Math.max(1, Number.parseInt(one("page") ?? "1", 10) || 1);
  const source = Number.parseInt(one("source_id") ?? "", 10);
  const active = one("active");
  return {
    search: bounded(one("search")), geography: bounded(one("geography")),
    category: allowedCategories.has(one("category") ?? "") ? one("category") as IndicatorQuery["category"] : undefined,
    frequency: allowedFrequencies.has(one("frequency") ?? "") ? one("frequency") as IndicatorQuery["frequency"] : undefined,
    source_id: source > 0 ? source : undefined,
    operational_is_active: active === "true" ? true : active === "false" ? false : undefined,
    limit, offset: (page - 1) * limit,
  };
}

export function historicalCutoff(date: string | undefined): string | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const cutoff = new Date(`${date}T23:59:59.999Z`);
  return Number.isFinite(cutoff.getTime()) && cutoff.toISOString().startsWith(date) ? cutoff.toISOString() : null;
}

export function visibleRevisionsAtCutoff(revisions: DataRevisionRead[], asOf: string | null): DataRevisionRead[] {
  if (asOf === null) return revisions;
  const cutoff = Date.parse(asOf);
  if (!Number.isFinite(cutoff)) return [];
  return revisions.filter((revision) => {
    const timestamp = Date.parse(revision.revision_timestamp);
    return Number.isFinite(timestamp) && timestamp <= cutoff;
  });
}

export function chartWindow(frequency: string, observedAt: string) {
  const end = new Date(observedAt); if (!Number.isFinite(end.getTime())) return null;
  const start = new Date(end);
  if (frequency === "daily") start.setUTCDate(start.getUTCDate() - 180);
  else if (frequency === "weekly") start.setUTCFullYear(start.getUTCFullYear() - 3);
  else if (frequency === "monthly") start.setUTCFullYear(start.getUTCFullYear() - 10);
  else if (frequency === "quarterly") start.setUTCFullYear(start.getUTCFullYear() - 30);
  else if (frequency === "annual") start.setUTCFullYear(start.getUTCFullYear() - 100);
  else start.setUTCFullYear(start.getUTCFullYear() - 5);
  return { start: start.toISOString(), end: end.toISOString() };
}

export async function loadCatalog(params: Record<string, string | string[] | undefined>, transport = createIndicatorTransport()) {
  try { const query = normalizeCatalogQuery(params); const response = await transport.catalog(query); return response.data ? { status: "ready" as const, data: response.data, query } : { status: "error" as const }; }
  catch { return { status: "error" as const }; }
}

export async function loadIndicatorDetail(seriesId: string, date: string | undefined, transport: IndicatorTransport = createIndicatorTransport()): Promise<IndicatorDetailResult> {
  if (!/^[1-9]\d*$/.test(seriesId)) return { status: "invalid" };
  const id = Number(seriesId); if (!Number.isSafeInteger(id)) return { status: "invalid" };
  try {
    const detailResult = await transport.detail(id);
    if (detailResult.status === 404) return { status: "not_found" };
    if (!detailResult.data || detailResult.data.curation.curation_status !== "reviewed_private") return { status: "unavailable" };
    const asOf = date ? historicalCutoff(date) : null;
    if (date && !asOf) return { status: "invalid" };
    const snapshotResult = await transport.snapshot(id, asOf ?? undefined);
    if (!snapshotResult.data) return { status: "unavailable" };
    const snapshot = snapshotResult.data;
    const window = snapshot.observed_at ? chartWindow(snapshot.frequency, snapshot.observed_at) : null;
    const [observationsResult, revisionsResult] = await Promise.all([
      window ? transport.observations(id, window.start, window.end, asOf ?? undefined) : Promise.resolve({ data: [], status: 200 }),
      snapshot.observation_identity?.revision_count ? transport.revisions(id, snapshot.observation_identity.observation_id) : Promise.resolve({ data: [], status: 200 }),
    ]);
    let relatedSection: RelatedSection = { status: "historical_not_supported" };
    if (asOf === null) {
      const relatedResult = await transport.related(id);
      if (relatedResult.data) {
        const lineagePairs = relatedResult.data.items.filter((item) => item.run_id && item.observation_id);
        const lineageResults = await Promise.all(lineagePairs.map(async (item) => [`${item.run_id}:${item.observation_id}`, await transport.lineage(item.run_id!, item.observation_id!)] as const));
        const lineages = Object.fromEntries(lineageResults.filter(([, result]) => result.data).map(([key, result]) => [key, result.data!]));
        relatedSection = { status: "current_available", related: relatedResult.data, lineages };
      } else relatedSection = { status: "unavailable" };
    }
    return { status: "ready", data: { detail: detailResult.data, snapshot, chart: observationsResult.data?.length ? { status: "ready", points: observationsResult.data } : { status: observationsResult.status === 200 ? "empty" : "error", points: [] }, revisions: visibleRevisionsAtCutoff(revisionsResult.data ?? [], asOf), relatedSection, asOf } };
  } catch { return { status: "unavailable" }; }
}
