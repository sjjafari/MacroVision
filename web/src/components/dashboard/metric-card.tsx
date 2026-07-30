import type {
  DashboardComparison,
  DashboardFreshness,
  DashboardMetricSummary,
} from "@/lib/dashboard/types";
import {
  formatExactDecimal,
  formatUtcTimestamp,
  safeSourceUrl,
} from "@/lib/dashboard/format";

const METRIC_REASONS: Record<string, string> = {
  configured_series_missing: "سری پیکربندی‌شده هنوز در پایگاه داده موجود نیست.",
  observation_missing: "برای این شاخص هنوز مشاهده‌ای ثبت نشده است.",
  current_observation_missing: "مقدار مشاهدهٔ جاری مفقود است.",
  persisted_derived_result_missing: "نتیجهٔ محاسبه‌شدهٔ ماندگاریافته موجود نیست.",
};

const COMPARISON_REASONS: Record<string, string> = {
  metric_unavailable: "به‌دلیل نبود نقطهٔ جاری، مقایسه در دسترس نیست.",
  previous_observation_missing: "مشاهدهٔ قبلی برای مقایسه موجود نیست.",
  previous_observation_has_no_value: "مشاهدهٔ قبلی مقدار قابل‌استفاده ندارد.",
  percentage_reference_is_zero: "مرجع مقایسه صفر است و درصد تغییر معنا ندارد.",
  absolute_change_not_representable: "اختلاف مطلق خارج از دامنهٔ عددی قابل‌نمایش است.",
  percentage_change_not_representable: "درصد تغییر خارج از دامنهٔ عددی قابل‌نمایش است.",
  derived_comparison_missing: "نتیجهٔ تحلیلی مقایسه موجود نیست.",
  derived_comparison_anchor_mismatch:
    "نقطهٔ تحلیلی دقیقاً به همان زمان مشاهده متصل نیست.",
  derived_comparison_frequency_mismatch: "تناوب شاخص و مقایسه با یکدیگر متفاوت است.",
};

function reasonText(reason: string | null, comparison = false): string {
  if (!reason) return comparison ? "مقایسه در دسترس است." : "نقطه در دسترس است.";
  return (
    (comparison ? COMPARISON_REASONS : METRIC_REASONS)[reason] ??
    "جزئیات این وضعیت با یک کد پایدار ثبت شده است."
  );
}

export function MetricValue({
  value,
  unit,
}: {
  value: string | null;
  unit: string | null;
}) {
  if (value === null) return <strong className="dashboard-missing-value">—</strong>;
  return (
    <div className="dashboard-value">
      <strong className="ltr" aria-label={value} title={value}>
        {formatExactDecimal(value)}
      </strong>
      {unit && <span>{unit}</span>}
    </div>
  );
}

export function MetricStateBadge({ metric }: { metric: DashboardMetricSummary }) {
  const labels = {
    available: "موجود",
    stale: "⚠ دادهٔ قدیمی",
    missing: "دادهٔ مفقود",
  } as const;
  return (
    <span className={`metric-state metric-state-${metric.state}`} role="status">
      {labels[metric.state]}
    </span>
  );
}

function ExactValue({ value }: { value: string }) {
  return (
    <span className="ltr exact-inline" aria-label={value} title={value}>
      {formatExactDecimal(value)}
    </span>
  );
}

export function MetricComparison({
  comparison,
}: {
  comparison: DashboardComparison;
}) {
  if (comparison.type === "none") return null;
  return (
    <section className="metric-comparison" aria-label="مقایسه">
      <div className="metric-comparison-title">
        <strong>{comparison.basis_label_fa}</strong>
        <span>{comparison.state}</span>
      </div>
      {comparison.state === "available" ? (
        <dl className="inline-facts">
          {comparison.reference_value !== null &&
            comparison.reference_value !== undefined && (
              <>
                <dt>مقدار مرجع</dt>
                <dd><ExactValue value={comparison.reference_value} /></dd>
              </>
            )}
          {comparison.derived_value !== null &&
            comparison.derived_value !== undefined && (
              <>
                <dt>مقدار تحلیلی</dt>
                <dd><ExactValue value={comparison.derived_value} /></dd>
              </>
            )}
          {comparison.absolute_change !== null &&
            comparison.absolute_change !== undefined && (
              <>
                <dt>تغییر مطلق</dt>
                <dd><ExactValue value={comparison.absolute_change} /></dd>
              </>
            )}
          {comparison.percentage_change !== null &&
            comparison.percentage_change !== undefined && (
              <>
                <dt>تغییر درصدی</dt>
                <dd><ExactValue value={comparison.percentage_change} />٪</dd>
              </>
            )}
        </dl>
      ) : (
        <p>{reasonText(comparison.state_reason, true)}</p>
      )}
      <small>
        لنگر:{" "}
        <b className="ltr">{comparison.anchor_policy}</b>
      </small>
    </section>
  );
}

export function MetricFreshness({
  freshness,
}: {
  freshness: DashboardFreshness;
}) {
  const labels = {
    current: "تازه",
    stale: "⚠ قدیمی",
    not_configured: "آستانه تعریف نشده",
    unavailable: "تازگی نامشخص",
  } as const;
  return (
    <div className="metric-freshness">
      <strong>{labels[freshness.status]}</strong>
      <span className="ltr">{freshness.policy}</span>
      {freshness.stale_after_days !== null && (
        <span>آستانه: {freshness.stale_after_days} روز</span>
      )}
    </div>
  );
}

export function MetricSource({ metric }: { metric: DashboardMetricSummary }) {
  if (!metric.source) {
    return metric.derived_identity ? (
      <p className="metric-source">خروجی ماندگاریافتهٔ MacroVision Analytics</p>
    ) : null;
  }
  const href = safeSourceUrl(metric.source.reference_url);
  return (
    <p className="metric-source">
      منبع:{" "}
      {href ? (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {metric.source.source_name}
        </a>
      ) : (
        metric.source.source_name
      )}{" "}
      <span className="ltr">({metric.source.source_code})</span>
      {metric.source.source_reference && (
        <> · <span className="ltr">{metric.source.source_reference}</span></>
      )}
    </p>
  );
}

function TimeFact({ label, value }: { label: string; value: string | null }) {
  const formatted = formatUtcTimestamp(value);
  if (!formatted || !value) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd title={value}><time dateTime={value}>{formatted}</time></dd>
    </>
  );
}

export function MetricCard({
  definitionLabel,
  metric,
}: {
  definitionLabel: string;
  metric: DashboardMetricSummary;
}) {
  const unit = metric.localized_unit_label ?? metric.unit;
  return (
    <article className={`dashboard-metric-card metric-${metric.state}`}>
      <header>
        <div>
          <h3>{definitionLabel}</h3>
          {metric.subtitle_fa && <p>{metric.subtitle_fa}</p>}
        </div>
        <MetricStateBadge metric={metric} />
      </header>
      <MetricValue value={metric.value} unit={unit} />
      {metric.state === "missing" && <p>{reasonText(metric.state_reason)}</p>}
      <MetricFreshness freshness={metric.freshness} />
      <MetricComparison comparison={metric.comparison} />
      <MetricSource metric={metric} />
      <dl className="metric-times">
        <TimeFact label="زمان مشاهده" value={metric.observed_at} />
        <TimeFact label="انتشار منبع" value={metric.source_publication_timestamp} />
        <TimeFact label="برش دانش MacroVision" value={metric.knowledge_cutoff} />
        <TimeFact label="برش محاسبهٔ Analytics" value={metric.calculation_cutoff} />
        <TimeFact label="پایان اجرای Analytics" value={metric.analytics_completed_at} />
      </dl>
      <details className="metric-evidence">
        <summary>جزئیات شواهد</summary>
        <dl>
          <dt>کلید شاخص</dt><dd className="ltr">{metric.metric_key}</dd>
          <dt>تناوب</dt><dd className="ltr">{metric.frequency ?? "—"}</dd>
          <dt>جغرافیا</dt><dd className="ltr">{metric.geography ?? "—"}</dd>
          {metric.raw_identity && (
            <>
              <dt>کد سری</dt><dd className="ltr">{metric.raw_identity.series_code}</dd>
              <dt>شناسه سری/نقطه</dt>
              <dd className="ltr">{metric.raw_identity.series_id ?? "—"} / {metric.raw_identity.observation_id ?? "—"}</dd>
            </>
          )}
          {metric.derived_identity && (
            <>
              <dt>کد تعریف</dt><dd className="ltr">{metric.derived_identity.definition_code}</dd>
              <dt>نسخه/اجرا/نقطه</dt>
              <dd className="ltr">{metric.derived_identity.definition_version ?? "—"} / {metric.derived_identity.run_id ?? "—"} / {metric.derived_identity.observation_id ?? "—"}</dd>
            </>
          )}
          <dt>کد دوره مقایسه</dt><dd className="ltr">{metric.comparison.basis_code}</dd>
          <dt>سیاست لنگر</dt><dd className="ltr">{metric.comparison.anchor_policy}</dd>
          {metric.comparison.state_reason && (
            <><dt>کد وضعیت مقایسه</dt><dd className="ltr">{metric.comparison.state_reason}</dd></>
          )}
        </dl>
      </details>
    </article>
  );
}
