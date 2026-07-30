import { PageHeader } from "@/components/page-header";
import { FeaturedSeriesChart } from "@/components/dashboard/featured-series-chart";
import { MetricCard } from "@/components/dashboard/metric-card";
import type {
  DashboardDefinition,
  DashboardMetricSummary,
  DashboardPageData,
} from "@/lib/dashboard/types";
import { formatUtcTimestamp } from "@/lib/dashboard/format";

function metricMap(data: DashboardPageData): Map<string, DashboardMetricSummary> {
  return new Map(
    data.summary.groups
      .flatMap((group) => group.metrics)
      .map((metric) => [metric.metric_key, metric]),
  );
}

export function DashboardSummaryHeader({ data }: { data: DashboardPageData }) {
  return (
    <section className="dashboard-summary-header" aria-label="وضعیت به‌روزرسانی داشبورد">
      <div>
        <span>تولید داشبورد</span>
        <strong>{formatUtcTimestamp(data.summary.generated_at)}</strong>
      </div>
      <div>
        <span>آخرین برش دانش</span>
        <strong>{formatUtcTimestamp(data.summary.latest_knowledge_cutoff) ?? "ناموجود"}</strong>
      </div>
      <div>
        <span>شاخص‌های قدیمی</span>
        <strong>{data.summary.stale_metric_count}</strong>
      </div>
    </section>
  );
}

export function DashboardGroupSection({
  group,
  summaries,
}: {
  group: DashboardDefinition["groups"][number];
  summaries: Map<string, DashboardMetricSummary>;
}) {
  return (
    <section className="dashboard-group" aria-labelledby={`group-${group.group_code}`}>
      <header>
        <p className="eyebrow ltr">{group.group_code}</p>
        <h2 id={`group-${group.group_code}`}>{group.title_fa}</h2>
      </header>
      <div className="dashboard-metric-grid">
        {group.metrics.map((definition) => {
          const metric = summaries.get(definition.metric_key);
          return metric ? (
            <MetricCard
              key={definition.metric_key}
              definitionLabel={definition.label_fa}
              metric={metric}
            />
          ) : null;
        })}
      </div>
    </section>
  );
}

export function DashboardUpdateSummary({ data }: { data: DashboardPageData }) {
  if (data.definition.dashboard_code !== "home") return null;
  const metrics = data.summary.groups.flatMap((group) => group.metrics);
  const updates = metrics
    .filter((metric) => metric.knowledge_cutoff || metric.analytics_completed_at)
    .toSorted((left, right) =>
      (right.knowledge_cutoff ?? right.analytics_completed_at ?? "").localeCompare(
        left.knowledge_cutoff ?? left.analytics_completed_at ?? "",
      ),
    )
    .slice(0, 5);
  if (!updates.length) return null;
  return (
    <section className="dashboard-updates" aria-labelledby="latest-updates-title">
      <h2 id="latest-updates-title">آخرین به‌روزرسانی‌ها</h2>
      <ol>
        {updates.map((metric) => (
          <li key={metric.metric_key}>
            <strong>{metric.label_fa}</strong>
            <time
              dateTime={metric.knowledge_cutoff ?? metric.analytics_completed_at ?? undefined}
            >
              {formatUtcTimestamp(
                metric.knowledge_cutoff ?? metric.analytics_completed_at,
              )}
            </time>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function DashboardPage({
  data,
  eyebrow,
  title,
  description,
}: {
  data: DashboardPageData;
  eyebrow: string;
  title: string;
  description: string;
}) {
  const summaries = metricMap(data);
  return (
    <div className="page-stack dashboard-page">
      <PageHeader
        eyebrow={eyebrow}
        title={title}
        description={`${description} — ${data.definition.description_fa}`}
        phase={2}
        privateOnly
      />
      <DashboardSummaryHeader data={data} />
      {data.definition.groups.map((group) => (
        <DashboardGroupSection
          key={group.group_code}
          group={group}
          summaries={summaries}
        />
      ))}
      <FeaturedSeriesChart chart={data.featuredChart} />
      <DashboardUpdateSummary data={data} />
    </div>
  );
}
