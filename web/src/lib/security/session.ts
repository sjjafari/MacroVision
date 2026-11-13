import "server-only";

import { createHmac, pbkdf2Sync, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

export type Role = "researcher" | "operator";
export type Session = { sub:string; role:Role; exp:number; csrf:string };
export const SESSION_COOKIE="mv_session";

function b64(value:Buffer|string){return Buffer.from(value).toString("base64url");}
function secret(){
  const value=process.env.MACROVISION_WEB_SESSION_SECRET?.trim();
  if(!value||value.length<32) throw new Error("MACROVISION_WEB_SESSION_SECRET must contain at least 32 characters");
  return value;
}
export function securityMode(){return process.env.MACROVISION_SECURITY_MODE==="public"?"public":"private";}

function sign(payload:string){return createHmac("sha256",secret()).update(payload).digest("base64url");}
export function issueSession(sub:string,role:Role):{token:string;session:Session}{
  const session={sub,role,exp:Math.floor(Date.now()/1000)+8*60*60,csrf:b64(randomBytes(24))};
  const payload=b64(JSON.stringify(session)); return {token:`${payload}.${sign(payload)}`,session};
}
export function verifySessionToken(token:string|undefined):Session|null{
  if(!token)return null; const [payload,signature,...rest]=token.split(".");
  if(!payload||!signature||rest.length)return null;
  const expected=Buffer.from(sign(payload)); const actual=Buffer.from(signature);
  if(expected.length!==actual.length||!timingSafeEqual(expected,actual))return null;
  try{const value=JSON.parse(Buffer.from(payload,"base64url").toString("utf8")) as Partial<Session>;
    if(typeof value.sub!=="string"||(value.role!=="researcher"&&value.role!=="operator")||typeof value.exp!=="number"||typeof value.csrf!=="string"||value.exp<=Math.floor(Date.now()/1000))return null;
    return value as Session;
  }catch{return null;}
}
export async function currentSession(){
  if(securityMode()==="private")return {sub:"private-network",role:"operator",exp:Number.MAX_SAFE_INTEGER,csrf:"private-network"} satisfies Session;
  const store=await cookies(); return verifySessionToken(store.get(SESSION_COOKIE)?.value);
}
export async function requireRole(role:Role,csrf?:string|null){
  const session=await currentSession(); if(!session)throw new Error("authentication_required");
  if(role==="operator"&&session.role!=="operator")throw new Error("authorization_required");
  if(securityMode()==="public"&&(!csrf||csrf!==session.csrf))throw new Error("csrf_invalid");
  return session;
}
export function verifyPassword(password:string){
  const encoded=process.env.MACROVISION_WEB_RESEARCH_PASSWORD_HASH?.trim();
  if(!encoded)return false; const [scheme,digest,iterationsRaw,saltRaw,hashRaw]=encoded.split("$");
  const iterations=Number(iterationsRaw);
  if(scheme!=="pbkdf2"||digest!=="sha256"||!Number.isInteger(iterations)||iterations<310000||!saltRaw||!hashRaw)return false;
  const expected=Buffer.from(hashRaw,"base64url"); const actual=pbkdf2Sync(password,Buffer.from(saltRaw,"base64url"),iterations,expected.length,"sha256");
  return expected.length===actual.length&&timingSafeEqual(expected,actual);
}
export function configuredUser(){return process.env.MACROVISION_WEB_RESEARCH_USER?.trim()??"";}
