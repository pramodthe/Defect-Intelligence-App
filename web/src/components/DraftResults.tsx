import {Link} from 'react-router-dom';
import {Row} from '../api/client';
import {MediaTiles, Notice} from './shared';

const labels:Record<string,string>={observation:'Observation / finding',requirements:'Applicable requirements',assessment:'Technical assessment',opinion:'Opinion',recommendation:'Recommendation'};

export function DraftChat({conversation,clarification,reply,setReply,submit,busy}:{conversation:Row[];clarification?:Row;reply:string;setReply:(text:string)=>void;submit:()=>void;busy:boolean}){
 return <section className="draft-chat" aria-label="Agent conversation">{conversation.map((turn,i)=><div key={i} className={'chat-turn '+turn.role}><small>{turn.role==='user'?'You':'Report assistant'}</small><p>{turn.text}</p></div>)}
  {clarification?<div className="chat-reply"><ul>{clarification.questions.map((q:Row)=><li key={q.key}>{q.question}</li>)}</ul><label>Your reply<textarea aria-label="Reply to the assistant" rows={3} value={reply} onChange={e=>setReply(e.target.value)} placeholder="Answer in your own words. You can say you do not know."/></label><button className="primary" disabled={busy||!reply.trim()} onClick={submit}>{busy?'Sending…':'Send reply'}</button></div>:null}
 </section>;
}

export function DraftFollowUp({clarification,facts,setFact,submit,busy}:{clarification:Row;facts:Record<string,string>;setFact:(key:string,value:string)=>void;submit:()=>void;busy:boolean}){
 const questions:Row[]=clarification.questions||clarification.missing.map((key:string)=>({key,label:key.replaceAll('_',' ')}));
 return <section className="draft-follow-up" aria-label="Follow-up questions"><h2>Tell me a little more about the building</h2><p>{clarification.message}</p>
  {questions.map(q=><label key={q.key}>{q.label}{q.hint?<small>{q.hint}</small>:null}{q.options?<select aria-label={q.label} value={facts[q.key]||''} onChange={e=>setFact(q.key,e.target.value)}><option value="">Choose an answer</option>{q.options.map((v:string)=><option key={v}>{v}</option>)}</select>:<input aria-label={q.label} value={facts[q.key]||''} onChange={e=>setFact(q.key,e.target.value)} placeholder="Enter a detail, or Unknown"/>}</label>)}
  <div className="form-row"><button className="primary" disabled={busy||questions.some(q=>!facts[q.key]?.trim())} onClick={submit}>{busy?'Continuing…':'Find evidence and draft'}</button><button onClick={()=>questions.forEach(q=>{if(!facts[q.key]?.trim())setFact(q.key,'Unknown')})}>Mark unanswered details as unknown</button></div><small>Your answers are recorded as declarations. Unknown details remain visible in the draft.</small>
 </section>;
}

export default function DraftResults({run}:{run:Row}){
 const draft=run.answer.draft;if(!draft)return null;
 const anchors:string[]=Array.from(new Set<string>(run.answer.claims.filter((c:Row)=>c.kind!=='inference').flatMap((c:Row)=>c.anchor_ids)));
 const observed=draft.facts.observations;
 return <section className="report-draft" aria-label="Cited report draft"><div className="draft-title"><h2>Report section draft</h2><span>For technical review</span></div>
  <p className="muted">{run.question}</p>
  {draft.publication_policy!=='draft-publication/2'?<Notice>This saved draft used an earlier validation process. Start a new draft before reusing it.</Notice>:null}
  <details className="draft-context"><summary>Building details used for this draft</summary>{Object.entries(draft.facts).map(([key,value])=>{const fact=value as Row;return <p key={key}><strong>{key.replaceAll('_',' ')}:</strong> {fact.value}<small> · {fact.provenance||fact.kind}</small></p>})}</details>
  {draft.status==='needs_evidence'?<Notice>There is not enough source support to produce a draft. Review the evidence gaps below.</Notice>:null}
  {draft.sections.map((section:Row)=><section className="draft-report-part" key={section.key} data-draft-section={section.key}><h3>{labels[section.key]}</h3>
   {section.key==='observation'?<div className="declared-observation"><small>Reported by you · inspection evidence not independently verified</small><p>{observed?.value&&observed.value.toLowerCase()!=='unknown'?observed.value:'Site-specific observations have not been supplied. The following source material describes the previous report.'}</p></div>:null}
   {section.key==='requirements'&&draft.requirements_coverage!=='supported'?<p className="draft-gap">Applicable original requirements have not been verified. Any provisions below are attributed to the previous report.</p>:null}
   {section.claims.filter((claim:Row)=>claim.kind!=='inference').map((claim:Row,i:number)=><div className="draft-paragraph" key={i}><p>{claim.text} <span className="draft-citations">{claim.anchor_ids.map((id:string)=><Link key={id} to={'/sources/'+id} aria-label={'Citation '+(anchors.indexOf(id)+1)}>[{anchors.indexOf(id)+1}]</Link>)}</span></p><details><summary>Quoted source support</summary><blockquote>{claim.quote}</blockquote>{claim.quote_anchor_id?<Link to={'/sources/'+claim.quote_anchor_id}>Inspect exact quotation ↗</Link>:null}</details></div>)}
   {!section.claims.some((claim:Row)=>claim.kind!=='inference')&&section.key!=='requirements'?<p className="muted">No verified source-backed paragraph is available for this part.</p>:null}
  </section>)}
  {draft.media.length?<section className="draft-report-part"><h3>Relevant original report figures</h3><p className="muted">Historical illustrations from the source report. They are not photographs of this project.</p><MediaTiles items={draft.media}/></section>:null}
  <p className="draft-gap">Source report approval for reuse has not been established. Check the applicability, evidence and proposed repair before approving this draft.</p>
 </section>;
}
