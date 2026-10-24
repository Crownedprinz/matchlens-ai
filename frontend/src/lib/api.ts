import { Analysis, Event, Forecast, FormResult, Match, Player } from "../types";
const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
export class ApiError extends Error { status:number; constructor(message:string,status:number){super(message);this.name="ApiError";this.status=status;} }
async function request<T>(path:string, init:RequestInit={}, signal?:AbortSignal):Promise<T>{
  const res=await fetch(`${base}${path}`,{...init,signal,cache:"no-store"});
  if(!res.ok){let message="API request failed";try{const body=await res.json();message=body.detail??message;}catch{message="API request failed";}throw new ApiError(message,res.status);}
  return res.json() as Promise<T>;
}
export const api = {
  matches:(signal?:AbortSignal)=>request<Match[]>("/matches",{},signal),
  match:(id:string,signal?:AbortSignal)=>request<Match>(`/matches/${id}`,{},signal),
  forecast:(id:string,minute:number,signal?:AbortSignal)=>request<Forecast>(`/matches/${id}/forecast?minute=${minute}`,{},signal),
  events:(id:string,signal?:AbortSignal)=>request<Event[]>(`/matches/${id}/events`,{},signal),
  form:(id:string,signal?:AbortSignal)=>request<{home:FormResult[];away:FormResult[]}>(`/matches/${id}/form`,{},signal),
  players:(id:string,signal?:AbortSignal)=>request<{home:Player[];away:Player[]}>(`/matches/${id}/players`,{},signal),
  analysis:(body:{match_id:string;audience:"fan"|"analyst"|"fantasy";question:string;minute:number},signal?:AbortSignal)=>request<Analysis>("/analysis",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)},signal),
};
