import { NextResponse } from "next/server";
import { createContentTransport } from "@/lib/content/server-transport";

export const runtime="nodejs";

export async function POST(request:Request){
  const origin=request.headers.get("origin");
  if(!origin||origin!==new URL(request.url).origin)return NextResponse.json({error:"origin_rejected"},{status:403});
  const form=await request.formData();
  if(String(form.get("website")??"").trim())return NextResponse.redirect(new URL("/fa/magazine?subscription=success",request.url),303);
  const email=String(form.get("email")??"").trim();
  if(email.length<3||email.length>320)return NextResponse.redirect(new URL("/fa/magazine?subscription=invalid",request.url),303);
  try{
    const result=await createContentTransport().subscribe(email);
    if(!result.data)return NextResponse.redirect(new URL("/fa/magazine?subscription=invalid",request.url),303);
    return NextResponse.redirect(new URL("/fa/magazine?subscription=success",request.url),303);
  }catch{
    return NextResponse.redirect(new URL("/fa/magazine?subscription=unavailable",request.url),303);
  }
}
