import "server-only";

import { createCompareTransport, type CompareTransport } from "./server-transport";
import type { CompareQuery } from "./types";

function one(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
function isoEndOfDay(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T23:59:59.999Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().startsWith(value) ? date.toISOString() : null;
}
function isoStartOfDay(value: string | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().startsWith(value) ? date.toISOString() : null;
}
export function normalizeCompareQuery(params: Record<string,string|string[]|undefined>): CompareQuery | null {
  const rawItems = params.items;
  const items = (Array.isArray(rawItems) ? rawItems : rawItems ? [rawItems] : [])
    .flatMap(item => item.split(",")).map(item => item.trim()).filter(Boolean);
  if (items.length === 0) return null;
  if (items.length > 4 || new Set(items).size !== items.length || items.some(item => !/^(raw|derived):[1-9]\d*$/.test(item))) return null;
  const start = isoStartOfDay(one(params.start));
  const end = isoEndOfDay(one(params.end));
  if (!start || !end || start > end) return null;
  const asOf = one(params.as_of) ? isoEndOfDay(one(params.as_of)) : null;
  if (one(params.as_of) && !asOf) return null;
  return { items, start, end, asOf: asOf ?? undefined };
}

export async function loadComparePage(params: Record<string,string|string[]|undefined>, transport: CompareTransport = createCompareTransport()) {
  const query = normalizeCompareQuery(params);
  try {
    const [catalog, definitions] = await Promise.all([transport.catalog(), transport.definitions()]);
    if (!catalog.data || !definitions.data) return { status: "error" as const };
    if (!query) return { status: "ready" as const, catalog: catalog.data, definitions: definitions.data, query: null, comparison: null };
    const comparison = await transport.comparison(query);
    if (!comparison.data) return { status: "comparison_error" as const, catalog: catalog.data, definitions: definitions.data, query };
    return { status: "ready" as const, catalog: catalog.data, definitions: definitions.data, query, comparison: comparison.data };
  } catch {
    return { status: "error" as const };
  }
}
