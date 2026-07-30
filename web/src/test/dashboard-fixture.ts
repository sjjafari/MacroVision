import type {
  DashboardDefinition,
  DashboardMetricSummary,
  DashboardPageData,
  DashboardSummary,
} from "@/lib/dashboard/types";

export const dashboardDefinition = {
  dashboard_code: "home",
  title_fa: "نمای اصلی",
  description_fa: "خلاصهٔ مرورشده",
  groups: [
    {
      group_code: "inflation",
      title_fa: "تورم",
      metrics: [
        {
          metric_key: "headline_cpi",
          kind: "raw",
          raw_series_code: "FRED.CPIAUCSL",
          label_fa: "شاخص قیمت مصرف‌کننده",
          subtitle_fa: "سطح شاخص",
          localized_unit_label: "واحد شاخص",
          featured_chart: true,
          freshness_policy: {
            type: "raw_series_stale_after_days",
            stale_after_days: null,
            age_basis: "observed_at",
          },
          comparison: {
            type: "previous_observation",
            basis_code: "previous_observation",
            basis_label_fa: "در مقایسه با مشاهدهٔ قبلی",
            anchor_policy: "previous_observation",
            derived_definition_code: null,
          },
        },
      ],
    },
  ],
} satisfies DashboardDefinition;

export function metricFixture(
  overrides: Partial<DashboardMetricSummary> = {},
): DashboardMetricSummary {
  return {
    metric_key: "headline_cpi",
    kind: "raw",
    label_fa: "شاخص قیمت مصرف‌کننده",
    subtitle_fa: "سطح شاخص",
    state: "available",
    state_reason: null,
    value: "1234567890.12345678",
    unit: "index",
    localized_unit_label: "واحد شاخص",
    frequency: "monthly",
    geography: "US",
    currency: null,
    observed_at: "2026-06-01T00:00:00Z",
    source_publication_timestamp: "2026-06-10T00:00:00Z",
    knowledge_cutoff: "2026-06-10T01:00:00Z",
    calculation_cutoff: null,
    analytics_completed_at: null,
    source: {
      source_id: 1,
      source_code: "FRED",
      source_name: "Federal Reserve Economic Data",
      source_reference: "CPIAUCSL",
      reference_url: "https://fred.stlouisfed.org/series/CPIAUCSL",
    },
    raw_identity: {
      series_id: 11,
      series_code: "FRED.CPIAUCSL",
      observation_id: 21,
    },
    derived_identity: null,
    freshness: {
      policy: "raw_series_stale_after_days",
      status: "current",
      stale_after_days: 45,
      age_basis: "observed_at",
      evaluated_at: "2026-06-11T00:00:00Z",
    },
    comparison: {
      type: "previous_observation",
      basis_code: "previous_observation",
      basis_label_fa: "در مقایسه با مشاهدهٔ قبلی",
      anchor_policy: "previous_observation",
      state: "available",
      state_reason: null,
      current_observed_at: "2026-06-01T00:00:00Z",
      reference_observation_id: 20,
      reference_observed_at: "2026-05-01T00:00:00Z",
      reference_value: "1234567880.12345678",
      absolute_change: "10.00000000",
      percentage_change: "0.00000081",
    },
    ...overrides,
  };
}

export function summaryFixture(
  metric = metricFixture(),
): DashboardSummary {
  return {
    dashboard_code: "home",
    generated_at: "2026-06-11T00:00:00Z",
    latest_knowledge_cutoff: "2026-06-10T01:00:00Z",
    stale_metric_count: metric.freshness.status === "stale" ? 1 : 0,
    groups: [
      {
        group_code: "inflation",
        title_fa: "تورم",
        metrics: [metric],
      },
    ],
  };
}

export function pageFixture(metric = metricFixture()): DashboardPageData {
  return {
    definition: dashboardDefinition,
    summary: summaryFixture(metric),
    featuredChart: {
      status: "available",
      metricKey: "headline_cpi",
      title: "شاخص قیمت مصرف‌کننده",
      sourceLabel: "Federal Reserve Economic Data",
      start: "2016-06-01T00:00:00.000Z",
      end: "2026-06-01T00:00:00.000Z",
      points: [
        {
          observedAt: "2026-05-01T00:00:00Z",
          exactValue: "1234567880.12345678",
          status: "present",
        },
        {
          observedAt: "2026-06-01T00:00:00Z",
          exactValue: null,
          status: "missing",
        },
      ],
    },
  };
}
