import { notFound } from "next/navigation";
import { createContentTransport } from "@/lib/content/server-transport";

export default async function ArticlePage({params}:{params:Promise<{slug:string}>}){
  const {slug}=await params; if(!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)||slug.length>160)notFound();
  let article=null; try{const result=await createContentTransport().article(slug);if(result.status===404)notFound();article=result.data;}catch{}
  if(!article)return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>مطلب در دسترس نیست</h1><p>بارگذاری محتوای منتشرشده انجام نشد.</p></div></section>;
  const paragraphs=article.body_fa.split(/\n{2,}/).map(value=>value.trim()).filter(Boolean);
  return <article className="editorial-article"><header><p className="eyebrow">{article.category}</p><h1>{article.title_fa}</h1><p className="article-dek">{article.dek_fa}</p><div className="article-meta"><span>{article.author_display_name}</span><time dateTime={article.published_at}>{new Intl.DateTimeFormat("fa-IR",{dateStyle:"long"}).format(new Date(article.published_at))}</time></div></header><div className="article-body">{paragraphs.map((paragraph,index)=><p key={index}>{paragraph}</p>)}</div><footer className="editorial-disclaimer">این مطلب محتوای پژوهشی/آموزشی است و توصیهٔ خرید یا فروش دارایی محسوب نمی‌شود.</footer></article>;
}
