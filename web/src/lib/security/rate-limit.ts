type Bucket={count:number;resetAt:number};
const buckets=new Map<string,Bucket>();
export function consumeRateLimit(key:string,limit:number,windowMs:number){
  const now=Date.now(); const current=buckets.get(key);
  if(!current||current.resetAt<=now){buckets.set(key,{count:1,resetAt:now+windowMs});return {allowed:true,retryAfter:0};}
  if(current.count>=limit)return {allowed:false,retryAfter:Math.max(1,Math.ceil((current.resetAt-now)/1000))};
  current.count+=1; return {allowed:true,retryAfter:0};
}
export function clientKey(request:Request){
  if(process.env.MACROVISION_TRUST_PROXY==="1"){
    const forwarded=request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
    if(forwarded)return forwarded.slice(0,80);
  }
  return "direct";
}
