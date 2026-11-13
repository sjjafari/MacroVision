import { CatalogPage } from "@/components/indicators/catalog-page";
import { loadCatalog } from "@/lib/indicators/loader";

export default async function IndicatorsPage({ searchParams }: { searchParams: Promise<Record<string,string|string[]|undefined>> }) {
  const result = await loadCatalog(await searchParams);
  if (result.status === "error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>کاتالوگ موقتاً در دسترس نیست</h1><p>اطلاعات خصوصی خطا نمایش داده نمی‌شود.</p></div></section>;
  return <CatalogPage data={result.data} query={result.query} />;
}
