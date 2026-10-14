export type Row = Record<string, any>;
export async function api<T = Row>(path:string, init:RequestInit = {}):Promise<T>{
  const headers=new Headers(init.headers); headers.set('X-Workspace-Request','1');
  if(init.body && !(init.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response=await fetch('/api'+path,{...init,headers});
  const result=await response.json();
  if(!response.ok) throw new Error(result.message || result.detail || 'Request failed');
  return result;
}
export const post=(path:string,body:unknown={})=>api(path,{method:'POST',body:JSON.stringify(body)});
export const put=(path:string,body:unknown)=>api(path,{method:'PUT',body:JSON.stringify(body)});
export const asset=(id:string)=>'/api/assets/'+encodeURIComponent(id)+'/content';
export const cpToUtf16=(text:string,offset:number)=>Array.from(text).slice(0,offset).join('').length;
