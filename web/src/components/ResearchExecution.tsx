import {Row} from '../api/client';
import {phaseStatus,runActive,runStopped} from './researchStatus';

export default function ResearchExecution({run,events}:{run:Row;events:Row[]}){
 const calls:Row[]=run.answer.model_calls||events.filter(e=>e.type==='model_completed').map(e=>e.payload);
 const tools:Row[]=run.answer.tool_calls||events.filter(e=>e.type==='tool_completed');
 return <section className="research-execution" aria-label="Research workflow">
  <h3>Research workflow</h3>
  <p>{calls.length?`${run.answer.provider==='fireworks'?'Fireworks':run.answer.provider==='openai'?'OpenAI':'Configured provider'} · ${calls[0].model||run.answer.model}`:runStopped(run.status)?'No completed model calls':run.status==='clarification_required'?'Waiting for project facts':'Waiting for model calls'}{calls.length?` · ${calls.length} completed model calls`:''}</p>
  {['interrupted','cancelled','failed'].includes(run.status)?<p className="run-stopped">Run stopped · retrieved evidence remains available.</p>:null}
  <ol>
   {run.mode==='draft'?<li>Check applicable original requirements · {tools.find(e=>e.payload.tool==='get_applicable_requirements')?.payload.coverage||'pending'}</li>:null}
   <li>Plan and search the report{tools.filter(e=>e.payload.tool==='search_precedents').map(e=><small key={e.sequence}> · {e.payload.result_count} passages retrieved</small>)}</li>
   <li>Read original sections and related evidence · {tools.filter(e=>e.payload.tool==='get_report_sections').length} section reads · {tools.filter(e=>e.payload.tool==='get_exact_source').length} exact passage reads</li>
   {run.mode==='draft'?<li>Check evidence sufficiency · {phaseStatus(run,events,'model_evidence_grade')}{run.answer.draft?.evidence_grade?.missing?.length?<small> · {run.answer.draft.evidence_grade.missing.join('; ')}</small>:null}</li>:null}
   <li>Draft the answer · {phaseStatus(run,events,'model_synthesis')}</li>
   <li>Check citations and review support · {phaseStatus(run,events,'model_verification')}</li>
  </ol>
  {!runActive(run.status)&&run.operations?.some((o:Row)=>o.state==='unknown')?<small>A provider request has an unconfirmed outcome. It will not be automatically replayed.</small>:null}
  {calls.length?<details><summary>Model responses and token usage</summary>{calls.map((c,i)=><p key={i}>{c.node.replaceAll('model_','').replaceAll('_',' ')} · {c.model||run.answer.model}<br/><small>{c.response_id||'No response identifier supplied'} · {c.usage?.input_tokens??'?'} input / {c.usage?.output_tokens??'?'} output tokens</small></p>)}</details>:null}
 </section>
}
