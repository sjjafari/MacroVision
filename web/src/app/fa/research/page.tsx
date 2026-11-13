import { ResearchLogin } from "@/components/research/research-login";
import { ResearchWorkspace } from "@/components/research/research-workspace";
import { loadResearch } from "@/lib/research/loader";
import { currentSession, securityMode } from "@/lib/security/session";

export default async function ResearchPage({searchParams=Promise.resolve({})}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}) {
  const params=await searchParams;
  const session=await currentSession();
  if(securityMode()==="public"&&!session) return <ResearchLogin invalid={(Array.isArray(params.auth)?params.auth[0]:params.auth)==="invalid"} />;
  const result=await loadResearch(params);
  if(result.status==="error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>فضای پژوهش در دسترس نیست</h1><p>جزئیات خطای خصوصی نمایش داده نمی‌شود.</p></div></section>;
  const rawError=Array.isArray(params.error)?params.error[0]:params.error;
  return <ResearchWorkspace series={result.series} definitions={result.definitions} selectedDefinition={result.selectedDefinition} run={result.run} observations={result.observations} lineage={result.lineage} error={rawError?.slice(0,200)} csrfToken={session?.csrf} />;
}
