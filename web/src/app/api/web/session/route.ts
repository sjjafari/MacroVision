import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { clientKey, consumeRateLimit } from "@/lib/security/rate-limit";
import { configuredUser, currentSession, issueSession, securityMode, SESSION_COOKIE, verifyPassword } from "@/lib/security/session";

export const runtime="nodejs";

function cookieOptions(){return {httpOnly:true,sameSite:"strict" as const,secure:process.env.NODE_ENV==="production",path:"/",maxAge:8*60*60};}
export async function POST(request:Request){
  if(securityMode()!=="public")return NextResponse.redirect(new URL("/fa/research",request.url),303);
  const form=await request.formData(); const action=String(form.get("action")??"login");
  if(action==="logout"){
    const session=await currentSession(); const csrf=String(form.get("csrf")??"");
    if(!session||csrf!==session.csrf)return NextResponse.json({error:"csrf_invalid"},{status:403});
    const response=NextResponse.redirect(new URL("/fa/research",request.url),303); response.cookies.set(SESSION_COOKIE,"",{...cookieOptions(),maxAge:0}); return response;
  }
  const rate=consumeRateLimit(`login:${clientKey(request)}`,5,10*60*1000);
  if(!rate.allowed)return NextResponse.json({error:"rate_limited"},{status:429,headers:{"retry-after":String(rate.retryAfter)}});
  const username=String(form.get("username")??"").trim(),password=String(form.get("password")??"");
  if(username!==configuredUser()||!verifyPassword(password))return NextResponse.redirect(new URL("/fa/research?auth=invalid",request.url),303);
  const {token}=issueSession(username,"operator"); const response=NextResponse.redirect(new URL("/fa/research",request.url),303); response.cookies.set(SESSION_COOKIE,token,cookieOptions()); return response;
}
