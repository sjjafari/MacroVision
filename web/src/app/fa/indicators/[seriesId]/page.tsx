import { IndicatorPlaceholder } from "@/components/indicator-placeholder";

export default async function IndicatorDetailPage({
  params,
}: {
  params: Promise<{ seriesId: string }>;
}) {
  const { seriesId } = await params;
  return <IndicatorPlaceholder seriesId={seriesId} />;
}
