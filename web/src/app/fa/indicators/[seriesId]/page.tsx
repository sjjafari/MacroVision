import { notFound } from "next/navigation";
import { IndicatorDetailPage as IndicatorDetailView } from "@/components/indicators/detail-page";
import { loadIndicatorDetail } from "@/lib/indicators/loader";

export default async function IndicatorDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ seriesId: string }>;
  searchParams: Promise<{ date?: string }>;
}) {
  const { seriesId } = await params;
  const result = await loadIndicatorDetail(seriesId, (await searchParams).date);
  if (result.status === "invalid" || result.status === "not_found") notFound();
  if (result.status !== "ready") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>شاخص در دسترس نیست</h1><p>دادهٔ تأییدنشده یا جزئیات فنی نمایش داده نمی‌شود.</p></div></section>;
  return <IndicatorDetailView data={result.data} />;
}
