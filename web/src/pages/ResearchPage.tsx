import {useEffect,useState} from 'react';
import {Link,useNavigate,useParams,useSearchParams} from 'react-router-dom';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,post,Row} from '../api/client';
import {Status,Notice,ErrorBox,SourceLinks,Excerpt,MediaTiles} from '../components/shared';
import ResearchExecution from '../components/ResearchExecution';
import ReportSectionResults from '../components/ReportSectionResults';
import DraftResults,{DraftFollowUp,DraftChat} from '../components/DraftResults';
import {researchError,runActive} from '../components/researchStatus';

function useData(path:string,enabled=true,interval?:number){return useQuery({queryKey:[path],queryFn:()=>api(path),enabled,refetchInterval:interval})}

export default function ResearchPage(){
 const{id}=useParams();const[params]=useSearchParams();const navigate=useNavigate();const qc=useQueryClient();
 const[question,setQuestion]=useState(params.get('question')||'');const[mode,setMode]=useState('draft');
 const[project,setProject]=useState('');const[part,setPart]=useState('');const[error,setError]=useState<unknown>();const[busy,setBusy]=useState(false);
 const[facts,setFacts]=useState<Record<string,string>>({});const[live,setLive]=useState<Row[]>([]);
 const[reply,setReply]=useState('');
 const[pendingReplyVersion,setPendingReplyVersion]=useState<number>();
 const{data:processing}=useData('/settings');const{data:projects}=useData('/projects');const{data:runs}=useData('/runs',true,3000);
 const{data:run}=useData('/runs/'+id,!!id,1000);const{data:events}=useData('/events/'+id,!!id,1200);
 const originalSections=useQuery({queryKey:['original-report-sections',id,(run?.evidence.items||[]).map((e:Row)=>e.id).join(',')],queryFn:()=>api('/runs/'+id+'/report-sections'),enabled:!!id&&run?.id===id,staleTime:Infinity});
 useEffect(()=>{if(!id||run&&!runActive(run.status))return;const stream=new EventSource('/api/runs/'+id+'/events');
  const receive=(event:MessageEvent)=>{try{setLive(prev=>[...prev.slice(-15),JSON.parse(event.data)])}catch{}};
  ['node_started','node_complete','model_started','model_completed','tool_started','tool_completed','tool_failed','clarification_required','complete','failed','cancelled'].forEach(t=>stream.addEventListener(t,receive));
  return()=>{stream.close();setLive([])};
 },[id,run?.status]);
 useEffect(()=>{setFacts({});setError(undefined);if(run){setQuestion(run.question);setMode(run.mode);setProject(run.project_id||'');setPart(run.part_id||'')}},[run?.id]);
 useEffect(()=>{setReply('')},[run?.id,run?.draft_context?.version]);
 useEffect(()=>{if(run?.status!=='clarification_required'||pendingReplyVersion!==run?.draft_context?.version)setPendingReplyVersion(undefined)},[run?.id,run?.status,run?.draft_context?.version]);
 async function start(){setBusy(true);setError(undefined);try{const result=await post('/questions',{question,mode,project_id:project||null,part_id:part||null,client_request_id:crypto.randomUUID()});navigate('/research/'+result.run_id);qc.invalidateQueries()}catch(e){setError(e)}finally{setBusy(false)}}
 const clarification=events?.items.findLast((e:Row)=>e.type==='clarification_required')?.payload;
 async function continueDraft(){if(!clarification)return;setBusy(true);setPendingReplyVersion(clarification.expected_context_version);setError(undefined);try{await post('/runs/'+id+'/resume',{expected_context_version:clarification.expected_context_version,...(run?.mode==='draft'?{message:reply}:{facts}),provenance:'User answers in the report assistant'});qc.invalidateQueries()}catch(e){setPendingReplyVersion(undefined);setError(e)}finally{setBusy(false)}}
 const selectedProject=projects?.items.find((p:Row)=>p.id===project);const isDraft=mode==='draft';
 const form=<div className="research-form"><h2>{isDraft?'Report writing assistant':'Ask the library'}</h2><p>{isDraft?'Describe the issue. I will ask for missing building details, find source material, and prepare a cited draft.':'Explore previous report evidence.'}</p>
  <div className="form-row"><label>Research mode<select aria-label="Research mode" value={mode} onChange={e=>setMode(e.target.value)}><option value="draft">Report drafting</option><option value="historical">Historical precedent</option><option value="current">Current building</option><option value="remedial">Proposed remedial work</option><option value="comparison">Compare assessments</option></select></label>
  <label>Project<select aria-label="Project" value={project} onChange={e=>{setProject(e.target.value);setPart('')}}><option value="">{isDraft?'Enter building details in this conversation':'Historical context only'}</option>{projects?.items.map((p:Row)=><option value={p.id} key={p.id}>{p.label}</option>)}</select></label>
  {project?<label>Building part<select aria-label="Building part" value={part} onChange={e=>setPart(e.target.value)}><option value="">Select part</option>{selectedProject?.parts.map((p:Row)=><option key={p.id} value={p.id}>{p.label}</option>)}</select></label>:null}</div>
  <textarea aria-label="Research question" rows={3} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Water ingress from the bathroom"/>
  <div className="form-row"><button className="primary" onClick={start} disabled={busy||question.trim().length<2||!!project&&!part}>{busy?'Starting…':isDraft?'Start drafting':'Start research'}</button>
  {id&&(runActive(run?.status)||run?.status==='clarification_required')?<button onClick={async()=>{try{await post('/runs/'+id+'/cancel');qc.invalidateQueries()}catch(e){setError(e)}}}>Cancel run</button>:null}
  <small>{processing?.text_provider==='disabled'?<Link to="/settings">Configure the report assistant</Link>:'Source-backed research and drafting'}</small></div></div>;
 const workflow=run?<ResearchExecution run={run} events={events?.items||[]}/>:null;
 return <div className={'research-layout'+(isDraft?' drafting-layout':'')}><section className="research-main">
  {run?<details className="saved-research-question"><summary>Issue and research controls</summary>{form}</details>:form}<ErrorBox error={error}/>
  {run?<div className="answer"><div className="result-count"><h3>{run.question}</h3><Status value={run.status}/></div>
   {run.stale?<Notice>This saved answer is stale. Start a new run to use the current library and project information.</Notice>:null}
   {run.error?<ErrorBox error={researchError(run,events?.items||[])}/>:null}
   {isDraft&&run.draft_context?.conversation.length?run.answer.draft?<details><summary>Conversation and building details</summary><DraftChat conversation={run.draft_context.conversation} reply={reply} setReply={setReply} submit={continueDraft} busy={busy}/></details>:<DraftChat conversation={run.draft_context.conversation} clarification={run.status==='clarification_required'?clarification:undefined} reply={reply} setReply={setReply} submit={continueDraft} busy={busy||pendingReplyVersion===clarification?.expected_context_version}/>:null}
   {!isDraft&&run.status==='clarification_required'&&clarification?<DraftFollowUp clarification={clarification} facts={facts} setFact={(key,value)=>setFacts(prev=>({...prev,[key]:value}))} submit={continueDraft} busy={busy}/>:null}
   {runActive(run.status)?workflow:null}
   {run.answer.draft?<DraftResults run={run}/>:null}
   {isDraft?<>
    {originalSections.data?.sections.length?<details className="research-secondary"><summary>Original report sections and source images</summary><ReportSectionResults data={originalSections.data} error={originalSections.error}/></details>:null}
    {!runActive(run.status)&&run.status!=='clarification_required'?<details className="research-secondary"><summary>Research steps and evidence checks</summary>{workflow}</details>:null}
   </>:<><ReportSectionResults data={originalSections.data} error={originalSections.error}/><details className="research-secondary"><summary>AI interpretation and research workflow</summary>{workflow}{run.answer.claims?.map((c:Row,i:number)=><section className="claim" key={i}><h3>{c.text}</h3><Status value={c.kind}/><blockquote>{c.quote||c.text}</blockquote><SourceLinks ids={c.anchor_ids}/></section>)}</details></>}
   {run.answer.gaps?.length?<section className="draft-evidence-gaps"><h3>Evidence still needed</h3><ul>{run.answer.gaps.map((gap:string)=><li key={gap}>{gap}</li>)}</ul></section>:null}
   <details><summary>Run trace and pinned versions</summary><p>Manifest: {run.manifest_id}</p><p>Graph: {run.graph_version} · checkpoint: {run.checkpoint_id||'Not recorded yet'}</p>{(events?.items||live).map((e:Row)=><div className="trace-row" key={e.sequence}>{e.sequence} · {e.type.replaceAll('_',' ')} · {e.payload.node||e.payload.tool||e.payload.outcome||''}</div>)}</details>
  </div>:<div className="empty"><h3>Start with the issue you are writing about</h3><p>For example: “water ingress from the bathroom”. Original sources and missing evidence remain inspectable alongside the draft.</p></div>}
 </section><aside className="research-evidence"><details open={!isDraft}><summary>Saved research</summary>{runs?.items.map((r:Row)=><Link className="history-row" key={r.id} to={'/research/'+r.id}><strong>{r.question}</strong><small>{r.mode} · {r.status}{r.stale?' · stale':''}</small></Link>)}</details>
  {run?.evidence.items?.length?<details><summary>Retrieved source evidence · {run.evidence.items.length} passages</summary>{run.evidence.items.map((e:Row)=><section className="evidence-row" key={e.id}><strong>{e.header}</strong><Excerpt text={e.text} max={300}/><SourceLinks ids={e.anchor_ids}/></section>)}</details>:null}
  {!isDraft&&run?.evidence.media?.length?<><h3>Original visuals</h3><MediaTiles items={run.evidence.media}/></>:null}
 </aside></div>;
}
