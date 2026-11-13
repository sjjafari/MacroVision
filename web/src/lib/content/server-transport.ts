import "server-only";
import { createServerApiClient } from "@/lib/api/server-client";

export function createContentTransport(){
  const client=createServerApiClient();
  return {
    async list(limit=20,offset=0,category?:string){
      const result=await client.GET("/api/v1/public/content/articles",{params:{query:{limit,offset,category}}});
      return {data:result.data??null,status:result.response.status};
    },
    async article(slug:string){
      const result=await client.GET("/api/v1/public/content/articles/{slug}",{params:{path:{slug}}});
      return {data:result.data??null,status:result.response.status};
    },
    async subscribe(email:string){
      const result=await client.POST("/api/v1/public/subscriptions",{body:{email,consent:true}});
      return {data:result.data??null,status:result.response.status};
    },
  };
}
