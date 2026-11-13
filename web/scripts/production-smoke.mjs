import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";

const upstreamPort = Number(process.env.SMOKE_UPSTREAM_PORT ?? "8100");
const webPort = Number(process.env.SMOKE_WEB_PORT ?? "3100");
const host = "127.0.0.1";
const decimal = "1234567890.12345678";
const webBase = `http://${host}:${webPort}`;
let queryObserved = false;
const upstreamMethods = [];
let relatedRequests = 0;
let lineageRequests = 0;

const indicatorSource = { source_id: 7, source_code: "FRED", source_name: "Federal Reserve Economic Data", reference_url: "https://fred.stlouisfed.org/series/CPIAUCSL" };
const catalogItem = { catalog_order: 1, curation_status: "reviewed_private", availability: "available", series_id: 11, series_code: "FRED.CPIAUCSL", display_name_fa: "شاخص قیمت مصرف‌کننده آمریکا", original_name: "Consumer Price Index for All Urban Consumers", description_fa: "معیار منتخب برای بررسی روند سطح قیمت‌ها", localized_unit_label: "واحد شاخص", category: "inflation", geography: "US", frequency: "monthly", unit: "index", seasonal_adjustment_status: "seasonally_adjusted", operational_is_active: true, source: indicatorSource, editorial_updated_at: "2026-08-01T00:00:00Z" };
const missingCatalogItem = { ...catalogItem, catalog_order: 2, availability: "configured_series_missing", series_id: null, series_code: "FRED.MISSING", display_name_fa: "شاخص در انتظار اتصال", original_name: null, source: null, operational_is_active: null };
function indicatorSnapshot(asOf = null) { return { mode: asOf ? "historical_as_of" : "current", requested_as_of: asOf, generated_at: "2026-08-01T12:00:00Z", state: asOf ? "available" : "stale", state_reason: asOf ? null : "stale_after_days_exceeded", value: "321.40000000", observation_identity: { series_id: 11, observation_id: 21, revision_count: 1 }, observed_at: "2026-06-01T00:00:00Z", source_publication_timestamp: null, knowledge_cutoff: asOf ?? "2026-06-02T00:00:00Z", unit: "index", localized_unit_label: "واحد شاخص", frequency: "monthly", geography: "US", source: indicatorSource, source_attribution_fa: "FRED", freshness: { evaluated_at: "2026-08-01T00:00:00Z", policy: "raw_series_stale_after_days", stale_after_days: 30, age_basis: "observed_at", status: asOf ? "current" : "stale" }, comparison: { type: "previous_observation", basis_code: "previous_observation", basis_label_fa: "مشاهدهٔ قبلی", anchor_policy: "previous_observation", state: "available", state_reason: null, current_observed_at: "2026-06-01T00:00:00Z", reference_observation_id: 20, reference_observed_at: "2026-05-01T00:00:00Z", reference_value: "320.10000000", absolute_change: "1.30000000", percentage_change: "0.40612309", derived_identity: null, derived_value: null, derived_observed_at: null, derived_calculation_cutoff: null, derived_completed_at: null } }; }

function dashboardDefinition(code) {
  return {
    dashboard_code: code,
    title_fa: `داشبورد ${code}`,
    description_fa: "خلاصهٔ مرورشده و ماندگاریافته",
    groups: [
      {
        group_code: "inflation",
        title_fa: "تورم",
        metrics: [
          {
            metric_key: `${code}_exact`,
            kind: code === "macro" ? "derived" : "raw",
            raw_series_code: code === "macro" ? null : "FRED.CPIAUCSL",
            derived_definition_code:
              code === "macro" ? "ANALYTICS.CPI.YOY" : null,
            label_fa: "مقدار دقیق",
            subtitle_fa: "نمایش بدون گردکردن",
            localized_unit_label: "واحد شاخص",
            comparison: {
              type: "previous_observation",
              basis_code: "previous_observation",
              basis_label_fa: "مشاهدهٔ قبلی",
              anchor_policy: "previous_observation",
              derived_definition_code: null,
            },
            freshness_policy: {
              type: "raw_series_stale_after_days",
              stale_after_days: null,
              age_basis: "observed_at",
            },
            featured_chart: true,
          },
          {
            metric_key: `${code}_missing`,
            kind: "raw",
            raw_series_code: "FRED.MISSING",
            label_fa: "دادهٔ مفقود",
            subtitle_fa: null,
            localized_unit_label: null,
            comparison: {
              type: "none",
              basis_code: "no_comparison",
              basis_label_fa: "بدون مقایسه",
              anchor_policy: "not_applicable",
              derived_definition_code: null,
            },
            freshness_policy: {
              type: "raw_series_stale_after_days",
              stale_after_days: null,
              age_basis: "observed_at",
            },
            featured_chart: false,
          },
          {
            metric_key: `${code}_mismatch`,
            kind: "raw",
            raw_series_code: "FRED.MISMATCH",
            label_fa: "مقایسهٔ ناهم‌تناوب",
            subtitle_fa: null,
            localized_unit_label: null,
            comparison: {
              type: "existing_derived_metric",
              basis_code: "year_over_year",
              basis_label_fa: "تغییر سالانه",
              anchor_policy: "same_observed_at",
              derived_definition_code: "ANALYTICS.TEST",
            },
            freshness_policy: {
              type: "raw_series_stale_after_days",
              stale_after_days: null,
              age_basis: "observed_at",
            },
            featured_chart: false,
          },
        ],
      },
    ],
  };
}

function metric(code, suffix, overrides = {}) {
  return {
    metric_key: `${code}_${suffix}`,
    kind: "raw",
    label_fa: suffix === "exact" ? "مقدار دقیق" : "شاخص آزمایشی",
    subtitle_fa: null,
    state: "available",
    state_reason: null,
    value: decimal,
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
      basis_label_fa: "مشاهدهٔ قبلی",
      anchor_policy: "previous_observation",
      state: "incomparable",
      state_reason: "percentage_reference_is_zero",
      current_observed_at: "2026-06-01T00:00:00Z",
      reference_observation_id: 20,
      reference_observed_at: "2026-05-01T00:00:00Z",
      reference_value: "0.00000000",
      absolute_change: decimal,
      percentage_change: null,
    },
    ...overrides,
  };
}

function dashboardSummary(code) {
  return {
    dashboard_code: code,
    generated_at: "2026-06-11T00:00:00Z",
    latest_knowledge_cutoff: "2026-06-10T01:00:00Z",
    stale_metric_count: 1,
    groups: [
      {
        group_code: "inflation",
        title_fa: "تورم",
        metrics: [
          metric(code, "exact", {
            ...(code === "markets"
              ? {
                  raw_identity: {
                    series_id: 12,
                    series_code: "FRED.MISSING",
                    observation_id: 22,
                  },
                }
              : {}),
            ...(code === "macro"
              ? {
                  kind: "derived",
                  source: null,
                  raw_identity: null,
                  derived_identity: {
                    definition_id: 31,
                    definition_code: "ANALYTICS.CPI.YOY",
                    definition_version: 2,
                    run_id: 41,
                    observation_id: 51,
                  },
                  calculation_cutoff: "2026-06-10T01:00:00Z",
                  analytics_completed_at: "2026-06-10T01:01:00Z",
                }
              : {}),
            state: "stale",
            state_reason: "series_stale",
            freshness: {
              policy: "raw_series_stale_after_days",
              status: "stale",
              stale_after_days: 45,
              age_basis: "observed_at",
              evaluated_at: "2026-06-11T00:00:00Z",
            },
          }),
          metric(code, "missing", {
            state: "missing",
            state_reason: "current_observation_missing",
            value: null,
            observed_at: null,
            source_publication_timestamp: null,
            knowledge_cutoff: null,
            source: null,
            raw_identity: {
              series_id: 12,
              series_code: "FRED.MISSING",
              observation_id: null,
            },
            freshness: {
              policy: "raw_series_stale_after_days",
              status: "unavailable",
              stale_after_days: null,
              age_basis: "observed_at",
              evaluated_at: "2026-06-11T00:00:00Z",
            },
            comparison: {
              type: "none",
              basis_code: "no_comparison",
              basis_label_fa: "بدون مقایسه",
              anchor_policy: "not_applicable",
              state: "missing",
              state_reason: "metric_unavailable",
            },
          }),
          metric(code, "mismatch", {
            comparison: {
              type: "existing_derived_metric",
              basis_code: "year_over_year",
              basis_label_fa: "تغییر سالانه",
              anchor_policy: "same_observed_at",
              state: "frequency_mismatch",
              state_reason: "derived_comparison_frequency_mismatch",
              current_observed_at: "2026-06-01T00:00:00Z",
            },
          }),
        ],
      },
    ],
  };
}

const upstream = createServer((request, response) => {
  upstreamMethods.push(request.method);
  if (request.method !== "GET") {
    response.writeHead(405, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { code: "read_only" } }));
    return;
  }
  const url = new URL(request.url ?? "/", `http://${host}`);
  if (url.pathname === "/api/v1/indicator-catalog") {
    const searched = url.searchParams.get("search");
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ limit: 12, offset: Number(url.searchParams.get("offset") ?? 0), total: searched === "none" ? 0 : 2, items: searched === "none" ? [] : [catalogItem, missingCatalogItem] })); return;
  }
  if (url.pathname === "/api/v1/indicator-catalog/11") {
    response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ curation: { curation_status: "reviewed_private", catalog_order: 1, editorial_updated_at: "2026-08-01T00:00:00Z", private_preview: true, public_eligibility: false }, presentation: { display_name_fa: catalogItem.display_name_fa, original_name: catalogItem.original_name, description_fa: catalogItem.description_fa, methodology_summary_fa: "تغییر سطح قیمت مصرف‌کننده با روش منبع رسمی", localized_unit_label: "واحد شاخص", source_attribution_fa: "FRED", seasonal_adjustment_status: "seasonally_adjusted", source_methodology_url: "https://fred.stlouisfed.org/series/CPIAUCSL" }, canonical: { series_id: 11, series_code: catalogItem.series_code, name: catalogItem.original_name, description: "Consumer price index", category: "inflation", geography: "US", frequency: "monthly", unit: "index", currency: null, is_active: true, stale_after_days: 30, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" }, source: { ...indicatorSource, description: "Official FRED source" } })); return;
  }
  if (url.pathname === "/api/v1/indicator-catalog/11/snapshot") { response.writeHead(200,{"content-type":"application/json"}); response.end(JSON.stringify(indicatorSnapshot(url.searchParams.get("as_of")))); return; }
  if (url.pathname === "/api/v1/indicator-catalog/11/related-derived") { relatedRequests += 1; response.writeHead(200,{"content-type":"application/json"}); response.end(JSON.stringify({series_id:11,series_code:catalogItem.series_code,items:[{relation_code:"year_over_year",relation_label_fa:"تورم سالانه",description_fa:"تغییر نسبت به سال قبل",state:"available",definition_id:31,definition_code:"ANALYTICS.CPI.YOY",definition_version:2,enabled:true,value:"3.25000000",observed_at:"2026-07-01T00:00:00Z",run_id:41,observation_id:50,calculation_cutoff:"2026-07-01T00:00:00Z",completed_at:"2026-07-01T01:00:00Z",missing_reason:null},{relation_code:"month_over_month",relation_label_fa:"تورم ماهانه",description_fa:"تغییر ماهانه",state:"persisted_result_missing",definition_id:32,definition_code:"ANALYTICS.CPI.MOM",definition_version:1,enabled:true,value:null,observed_at:null,run_id:null,observation_id:null,calculation_cutoff:null,completed_at:null,missing_reason:"definition_source_mismatch"}]})); return; }
  if (url.pathname === "/api/v1/data-series/11/observations/21/revisions") { response.writeHead(200,{"content-type":"application/json"}); response.end(JSON.stringify([{id:1,observation_id:21,sequence:1,previous_value:"321.30000000",revised_value:"321.35000000",previous_status:"present",revised_status:"present",revision_timestamp:"2026-06-03T00:00:00Z",reason:"source_revision",source_reference:"FRED",import_batch_id:1,publication_timestamp:null,provider_vintage_start:"2026-06-02",provider_vintage_end:"2026-06-02",provider_metadata:{}},{id:2,observation_id:21,sequence:2,previous_value:"321.35000000",revised_value:"999.99000000",previous_status:"present",revised_status:"present",revision_timestamp:"2026-07-01T00:00:00Z",reason:"future_revision",source_reference:"FRED",import_batch_id:2,publication_timestamp:null,provider_vintage_start:"2026-07-01",provider_vintage_end:"2026-07-01",provider_metadata:{}}])); return; }
  if (url.pathname === "/api/v1/analytics-runs/41/observations/50/lineage") { lineageRequests += 1; response.writeHead(200,{"content-type":"application/json"}); response.end(JSON.stringify({run_id:41,observation_id:50,limit:100,offset:0,items:[{id:1,input_alias:"cpi",input_position:0,lineage_position:0,source_knowledge_timestamp:"2026-07-01T00:00:00Z",source_observation_id:21,source_revision_id:1,source_version_id:1,source_version_kind:"raw_observation"}]})); return; }
  if (url.pathname === "/api/v1/data-series/11/observations/as-of") { request.url = `/api/v1/data-series/11/observations?${url.searchParams}`; }
  const dashboardMatch = request.url?.match(
    /^\/api\/v1\/dashboards\/(home|markets|macro)(\/summary)?$/,
  );
  if (dashboardMatch) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify(
        dashboardMatch[2]
          ? dashboardSummary(dashboardMatch[1])
          : dashboardDefinition(dashboardMatch[1]),
      ),
    );
    return;
  }
  if (request.url?.startsWith("/api/v1/data-series/11/observations?")) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify([
        {
          id: 20,
          series_id: 11,
          observed_at: "2026-05-01T00:00:00Z",
          publication_timestamp: null,
          ingestion_timestamp: "2026-05-02T00:00:00Z",
          provider_vintage_start: null,
          provider_vintage_end: null,
          provider_metadata: {},
          value: "1234567880.12345678",
          status: "present",
          source_reference: "CPIAUCSL",
          revision_count: 0,
        },
        {
          id: 21,
          series_id: 11,
          observed_at: "2026-06-01T00:00:00Z",
          publication_timestamp: null,
          ingestion_timestamp: "2026-06-02T00:00:00Z",
          provider_vintage_start: null,
          provider_vintage_end: null,
          provider_metadata: {},
          value: null,
          status: "missing",
          source_reference: "CPIAUCSL",
          revision_count: 0,
        },
      ]),
    );
    return;
  }
  if (request.url?.startsWith("/api/v1/data-series/12/observations?")) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify([
        {
          id: 22,
          series_id: 12,
          observed_at: "2026-06-01T00:00:00Z",
          publication_timestamp: null,
          ingestion_timestamp: "2026-06-02T00:00:00Z",
          provider_vintage_start: null,
          provider_vintage_end: null,
          provider_metadata: {},
          value: decimal,
          status: "missing",
          source_reference: null,
          revision_count: 0,
        },
      ]),
    );
    return;
  }
  if (request.url?.startsWith("/api/v1/data-series/13/observations?")) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end("[]");
    return;
  }
  if (request.url?.startsWith("/api/v1/analytics-runs/41/observations?")) {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        definition_id: 31,
        definition_version: 2,
        run_id: 41,
        limit: 200,
        offset: 0,
        items: [
          {
            id: 50,
            run_id: 41,
            definition_version_id: 61,
            observed_at: "2026-05-01T00:00:00Z",
            value: "1234567880.12345678",
            status: "present",
            missing_reason: null,
            created_at: "2026-06-10T01:01:00Z",
          },
          {
            id: 51,
            run_id: 41,
            definition_version_id: 61,
            observed_at: "2026-06-01T00:00:00Z",
            value: null,
            status: "missing",
            missing_reason: "source_missing",
            created_at: "2026-06-10T01:01:00Z",
          },
        ],
      }),
    );
    return;
  }
  if (request.url === "/api/v1/smoke?probe=preserved") {
    queryObserved = true;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ value: decimal, query: "preserved" }));
    return;
  }
  if (request.url === "/api/v1/smoke/failure") {
    response.writeHead(409, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { code: "intentional_conflict" } }));
    return;
  }
  if (request.url === "/api/v1/smoke/redirect-relative") {
    response.writeHead(307, {
      location: "/api/v1/smoke/target?kind=relative&query=preserved",
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/redirect-absolute") {
    response.writeHead(308, {
      location: `http://${host}:${upstreamPort}/api/v1/smoke/target?kind=absolute`,
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/redirect-external") {
    response.writeHead(302, {
      location: "https://attacker.invalid/collect?secret=destination",
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/method") {
    response.writeHead(405, {
      allow: "GET, HEAD",
      "content-type": "application/json",
    });
    response.end(JSON.stringify({ error: { code: "method_not_allowed" } }));
    return;
  }
  response.writeHead(404, { "content-type": "application/json" });
  response.end(JSON.stringify({ error: { code: "not_found" } }));
});

async function listen(server, port) {
  await new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolvePromise);
  });
}

async function close(server) {
  await new Promise((resolvePromise) => server.close(resolvePromise));
}

async function waitForApplication() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`${webBase}/fa`);
      if (response.ok) return;
    } catch {
      // The application is still starting.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Built Next.js application did not become ready.");
}

await listen(upstream, upstreamPort);
const nextProcess = spawn(
  process.execPath,
  [resolve("node_modules", "next", "dist", "bin", "next"), "start", "-H", host, "-p", String(webPort)],
  {
    cwd: process.cwd(),
    env: {
      ...process.env,
      MACROVISION_BACKEND_URL: `http://${host}:${upstreamPort}`,
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);

nextProcess.stdout.resume();
nextProcess.stderr.resume();

try {
  await waitForApplication();

  const root = await fetch(`${webBase}/`, { redirect: "manual" });
  if (![307, 308].includes(root.status) || root.headers.get("location") !== "/fa") {
    throw new Error(`Unexpected root redirect: ${root.status} ${root.headers.get("location")}`);
  }

  const staticRoutes = [
    "/fa",
    "/fa/markets",
    "/fa/macro",
    "/fa/indicators",
    "/fa/indicators/11",
    "/fa/compare",
    "/fa/research",
    "/fa/methodology",
    "/fa/about",
  ];
  for (const route of staticRoutes) {
    const response = await fetch(`${webBase}${route}`);
    if (!response.ok) throw new Error(`${route} returned ${response.status}`);
    const html = await response.text();
    if (!html.includes('lang="fa"') || !html.includes('dir="rtl"')) {
      throw new Error(`${route} does not render the Persian RTL document contract.`);
    }
    if (html.includes(`http://${host}:${upstreamPort}`)) {
      throw new Error(`${route} exposed the server-only backend URL.`);
    }
    if (["/fa", "/fa/markets", "/fa/macro"].includes(route)) {
      if (
        !html.includes("1234567890.12345678") ||
        !html.includes("دادهٔ مفقود") ||
        !html.includes("دادهٔ قدیمی") ||
        html.includes("داده هنوز بارگذاری نشده است")
      ) {
        throw new Error(`${route} did not render the connected dashboard contract.`);
      }
      if (
        route === "/fa/markets" &&
        !html.includes("chart_has_no_present_values")
      ) {
        throw new Error("Markets did not render the all-missing chart state.");
      }
      if (
        route !== "/fa/markets" &&
        !html.includes("جدول متنی داده‌های نمودار")
      ) {
        throw new Error(`${route} did not render exact chart evidence.`);
      }
      if (html.includes(">0<")) {
        throw new Error(`${route} mapped missing dashboard data to zero.`);
      }
    }
  }
  if (relatedRequests < 1 || lineageRequests < 1) throw new Error("Current indicator did not exercise related-derived and lineage reads.");
  const currentRelatedRequests = relatedRequests;
  const currentLineageRequests = lineageRequests;
  const historicalIndicator = await fetch(`${webBase}/fa/indicators/11?date=2026-06-30`);
  const historicalHtml = await historicalIndicator.text();
  if (!historicalIndicator.ok || !historicalHtml.includes("321.40000000") || !historicalHtml.includes("2026-06-30T23:59:59.999Z") || !historicalHtml.includes("321.35000000") || historicalHtml.includes("999.99000000") || historicalHtml.includes("3.25000000") || !historicalHtml.includes("Lineage") || relatedRequests !== currentRelatedRequests || lineageRequests !== currentLineageRequests) throw new Error("Historical indicator cutoff or current-derived isolation contract failed.");

  const proxyResponse = await fetch(`${webBase}/api/v1/smoke?probe=preserved`);
  const proxyBytes = await proxyResponse.text();
  if (!proxyResponse.ok || !queryObserved || !proxyBytes.includes(`"${decimal}"`)) {
    throw new Error("Proxy did not preserve query or exact Decimal JSON string.");
  }
  const emptyObservationResponse = await fetch(
    `${webBase}/api/v1/data-series/13/observations?limit=200&offset=0`,
  );
  if (
    !emptyObservationResponse.ok ||
    (await emptyObservationResponse.text()) !== "[]"
  ) {
    throw new Error("Fake upstream empty chart observation contract failed.");
  }

  const conflict = await fetch(`${webBase}/api/v1/smoke/failure`);
  const conflictBody = await conflict.text();
  if (conflict.status !== 409 || !conflictBody.includes("intentional_conflict")) {
    throw new Error("Proxy did not preserve the non-200 status and safe error body.");
  }

  const relativeRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-relative`, {
    redirect: "manual",
  });
  if (
    relativeRedirect.status !== 307 ||
    relativeRedirect.headers.get("location") !==
      "/api/v1/smoke/target?kind=relative&query=preserved"
  ) {
    throw new Error("Proxy did not safely rewrite the relative backend redirect.");
  }

  const absoluteRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-absolute`, {
    redirect: "manual",
  });
  const absoluteLocation = absoluteRedirect.headers.get("location");
  if (
    absoluteRedirect.status !== 308 ||
    absoluteLocation !== "/api/v1/smoke/target?kind=absolute" ||
    absoluteLocation.includes(`${host}:${upstreamPort}`)
  ) {
    throw new Error("Proxy did not safely rewrite the absolute backend redirect.");
  }

  const externalRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-external`, {
    redirect: "manual",
  });
  const externalBody = await externalRedirect.text();
  if (
    externalRedirect.status !== 502 ||
    externalRedirect.headers.has("location") ||
    externalBody.includes("attacker.invalid") ||
    externalBody.includes("secret=destination")
  ) {
    throw new Error("Proxy did not fail closed for an external backend redirect.");
  }

  const methodNotAllowed = await fetch(`${webBase}/api/v1/smoke/method`);
  if (
    methodNotAllowed.status !== 405 ||
    methodNotAllowed.headers.get("allow") !== "GET, HEAD"
  ) {
    throw new Error("Proxy did not preserve the safe Allow header on a 405 response.");
  }

  const buildManifest = await readFile(resolve(".next", "build-manifest.json"), "utf8");
  if (buildManifest.includes(`http://${host}:${upstreamPort}`)) {
    throw new Error("Backend URL leaked into a client build manifest.");
  }
  const clientAssetRoot = resolve(".next", "static");
  const clientAssets = await readdir(clientAssetRoot, { recursive: true });
  for (const asset of clientAssets.filter((name) => name.endsWith(".js"))) {
    const contents = await readFile(resolve(clientAssetRoot, asset), "utf8");
    if (contents.includes(`http://${host}:${upstreamPort}`)) {
      throw new Error(`Backend URL leaked into client asset ${asset}.`);
    }
  }
  if (upstreamMethods.some((method) => !["GET", "HEAD"].includes(method))) {
    throw new Error("A dashboard issued a mutation to the fake upstream.");
  }

  const visualHoldMs = Number(process.env.SMOKE_VISUAL_HOLD_MS ?? "0");
  if (visualHoldMs > 0) {
    console.log(`Visual smoke server ready at ${webBase}; indicator detail: ${webBase}/fa/indicators/11.`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, visualHoldMs));
  }

  console.log(
    "Production smoke passed: connected dashboards, nine routes, safe proxying, chart gaps, and exact Decimal.",
  );
} finally {
  nextProcess.kill();
  await close(upstream);
  await new Promise((resolvePromise) => {
    if (nextProcess.exitCode !== null) {
      resolvePromise();
      return;
    }
    nextProcess.once("exit", resolvePromise);
    setTimeout(resolvePromise, 3_000);
  });
}
