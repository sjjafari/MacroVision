import "server-only";

import {
  createDashboardReadTransport,
  type DashboardReadTransport,
} from "@/lib/dashboard/server-transport";
import type {
  ChartPoint,
  DashboardCode,
  DashboardDefinition,
  DashboardMetricDefinition,
  DashboardMetricSummary,
  DashboardPageResult,
  DashboardSummary,
  FeaturedChartData,
} from "@/lib/dashboard/types";

const DASHBOARD_CODES = new Set<DashboardCode>(["home", "markets", "macro"]);

function uniqueKeys(values: string[]): boolean {
  return values.length === new Set(values).size;
}

function validateContract(
  code: DashboardCode,
  definition: DashboardDefinition,
  summary: DashboardSummary,
): boolean {
  if (definition.dashboard_code !== code || summary.dashboard_code !== code) return false;
  const definitionGroups = definition.groups.map((group) => group.group_code);
  const summaryGroups = summary.groups.map((group) => group.group_code);
  if (!uniqueKeys(definitionGroups) || !uniqueKeys(summaryGroups)) return false;
  const allDefinitionMetrics = definition.groups.flatMap((group) =>
    group.metrics.map((metric) => metric.metric_key),
  );
  const allSummaryMetrics = summary.groups.flatMap((group) =>
    group.metrics.map((metric) => metric.metric_key),
  );
  if (!uniqueKeys(allDefinitionMetrics) || !uniqueKeys(allSummaryMetrics)) {
    return false;
  }
  const featuredMetrics = definition.groups
    .flatMap((group) => group.metrics)
    .filter((metric) => metric.featured_chart);
  if (featuredMetrics.length > 1) return false;
  if (
    definitionGroups.length !== summaryGroups.length ||
    definitionGroups.some((group) => !summaryGroups.includes(group))
  ) {
    return false;
  }
  for (const group of definition.groups) {
    const summaryGroup = summary.groups.find(
      (candidate) => candidate.group_code === group.group_code,
    );
    if (!summaryGroup) return false;
    const definitionMetrics = group.metrics.map((metric) => metric.metric_key);
    const summaryMetrics = summaryGroup.metrics.map((metric) => metric.metric_key);
    if (!uniqueKeys(definitionMetrics) || !uniqueKeys(summaryMetrics)) return false;
    if (
      definitionMetrics.length !== summaryMetrics.length ||
      definitionMetrics.some((metric) => !summaryMetrics.includes(metric))
    ) {
      return false;
    }
  }
  return true;
}

function featuredMetric(
  definition: DashboardDefinition,
  summary: DashboardSummary,
): [DashboardMetricDefinition, DashboardMetricSummary] | null {
  const configured = definition.groups.flatMap((group) =>
    group.metrics
      .filter((metric) => metric.featured_chart)
      .map((metric) => ({ groupCode: group.group_code, metric })),
  );
  if (configured.length !== 1) return null;
  const { groupCode, metric } = configured[0];
  const resolved = summary.groups
    .find((group) => group.group_code === groupCode)
    ?.metrics.find((candidate) => candidate.metric_key === metric.metric_key);
  return resolved ? [metric, resolved] : null;
}

function normalizeChartPoints(
  points: Array<{ observed_at: string; value: string | null; status: string }>,
): ChartPoint[] {
  return points.map((point) => ({
    observedAt: point.observed_at,
    exactValue: point.value,
    status: point.status === "present" ? "present" : "missing",
  }));
}

function chartFromPoints(
  metric: DashboardMetricSummary,
  window: { start: string; end: string },
  points: ChartPoint[],
): FeaturedChartData {
  if (points.length === 0) {
    return { status: "empty", reason: "chart_observations_empty" };
  }
  if (
    !points.some(
      (point) => point.status === "present" && point.exactValue !== null,
    )
  ) {
    return { status: "empty", reason: "chart_has_no_present_values" };
  }
  return {
    status: "available",
    metricKey: metric.metric_key,
    title: metric.label_fa,
    sourceLabel: metric.source?.source_name ?? null,
    start: window.start,
    end: window.end,
    points,
  };
}

export function chartWindow(
  frequency: DashboardMetricSummary["frequency"],
  observedAt: string,
): { start: string; end: string } | null {
  if (!frequency || frequency === "irregular") return null;
  const end = new Date(observedAt);
  if (!Number.isFinite(end.getTime())) return null;
  const start = new Date(end);
  if (frequency === "daily") start.setUTCDate(start.getUTCDate() - 180);
  if (frequency === "weekly") start.setUTCFullYear(start.getUTCFullYear() - 3);
  if (frequency === "monthly") start.setUTCFullYear(start.getUTCFullYear() - 10);
  if (frequency === "quarterly") start.setUTCFullYear(start.getUTCFullYear() - 30);
  if (frequency === "annual") start.setUTCFullYear(start.getUTCFullYear() - 100);
  return { start: start.toISOString(), end: end.toISOString() };
}

async function loadFeaturedChart(
  definition: DashboardDefinition,
  summary: DashboardSummary,
  transport: DashboardReadTransport,
): Promise<FeaturedChartData> {
  const pair = featuredMetric(definition, summary);
  if (!pair) return { status: "empty", reason: "featured_metric_unresolved" };
  const [configured, metric] = pair;
  if (metric.state === "missing" || !metric.observed_at) {
    return { status: "empty", reason: "featured_metric_missing" };
  }
  const window = chartWindow(metric.frequency, metric.observed_at);
  if (!window) return { status: "empty", reason: "featured_metric_irregular" };
  try {
    let points: ChartPoint[];
    if (configured.kind === "raw" && metric.raw_identity?.series_id) {
      const response = await transport.rawObservations(
        metric.raw_identity.series_id,
        window.start,
        window.end,
      );
      if (!response.data) return { status: "error", reason: "chart_read_failed" };
      points = normalizeChartPoints(response.data);
    } else if (configured.kind === "derived") {
      const identity = metric.derived_identity;
      if (
        !identity ||
        identity.definition_id === null ||
        identity.definition_version === null ||
        identity.run_id === null
      ) {
        return { status: "empty", reason: "featured_metric_identity_missing" };
      }
      const response = await transport.derivedRunObservations(
        identity.run_id,
        window.start,
        window.end,
      );
      if (!response.data) return { status: "error", reason: "chart_read_failed" };
      if (
        response.data.run_id !== identity.run_id ||
        response.data.definition_id !== identity.definition_id ||
        response.data.definition_version !== identity.definition_version
      ) {
        return { status: "error", reason: "chart_identity_mismatch" };
      }
      points = normalizeChartPoints(response.data.items);
    } else {
      return { status: "empty", reason: "featured_metric_identity_missing" };
    }
    return chartFromPoints(metric, window, points);
  } catch {
    return { status: "error", reason: "chart_read_failed" };
  }
}

export async function loadDashboardPage(
  requestedCode: string,
  transport: DashboardReadTransport = createDashboardReadTransport(),
): Promise<DashboardPageResult> {
  if (!DASHBOARD_CODES.has(requestedCode as DashboardCode)) {
    return { status: "error", code: "invalid_dashboard" };
  }
  const code = requestedCode as DashboardCode;
  try {
    const [definitionResponse, summaryResponse] = await Promise.all([
      transport.definition(code),
      transport.summary(code),
    ]);
    if (definitionResponse.status === 404 || summaryResponse.status === 404) {
      return { status: "error", code: "not_found" };
    }
    if (!definitionResponse.data || !summaryResponse.data) {
      return { status: "error", code: "unavailable" };
    }
    if (!validateContract(code, definitionResponse.data, summaryResponse.data)) {
      return { status: "error", code: "invalid_contract" };
    }
    const featuredChart = await loadFeaturedChart(
      definitionResponse.data,
      summaryResponse.data,
      transport,
    );
    return {
      status: "ready",
      data: {
        definition: definitionResponse.data,
        summary: summaryResponse.data,
        featuredChart,
      },
    };
  } catch {
    return { status: "error", code: "unavailable" };
  }
}
