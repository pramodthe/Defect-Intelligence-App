import {Row} from '../api/client';

export const runActive=(status:string)=>['queued','running'].includes(status);
export const runStopped=(status:string)=>['interrupted','cancelled','partial','complete','failed'].includes(status);

export function phaseStatus(run:Row,events:Row[],node:string):string{
 const starts=events.filter(e=>e.type==='model_started'&&e.payload.node===node);
 const ends=events.filter(e=>e.type==='model_completed'&&e.payload.node===node);
 const latestStart=starts.at(-1)?.sequence??-1;const latestEnd=ends.at(-1)?.sequence??-1;
 if(latestStart>latestEnd){
  if(runStopped(run.status))return /timeout|timed out/i.test(run.error||'')?'timed out':'interrupted';
  return 'running';
 }
 if(latestEnd>=0||run.answer?.model_calls?.some((c:Row)=>c.node===node))return 'completed';
 if(node==='model_synthesis'&&run.answer?.synthesis==='unavailable')return 'source excerpts only';
 return runStopped(run.status)?'not run':run.status==='clarification_required'?'waiting for project facts':'pending';
}

export function researchError(run:Row,events:Row[]):string|undefined{
 if(!run.error)return undefined;
 if(!/timeout|timed out/i.test(run.error))return run.error;
 const started=events.filter(e=>['model_started','node_started','tool_started'].includes(e.type)).at(-1)?.payload;
 const node=started?.node||started?.tool;
 const operation=run.operations?.filter((o:Row)=>o.node===node&&o.state==='unknown').at(-1);
 const stage=node==='model_synthesis'?'drafting the answer':node==='model_verification'?'verifying the answer':node==='model_planning'?'planning retrieval':'processing';
 const limit=operation?.seconds_reserved;
 return `This run stopped while ${stage}${limit?` after the ${limit}-second response limit`:''}. Retrieved evidence is saved. No retry is running.`;
}
