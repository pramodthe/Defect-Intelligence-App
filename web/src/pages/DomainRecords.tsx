import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Link,useSearchParams} from 'react-router-dom';
import {api,Row} from '../api/client';
import {ErrorBox,Notice,SourceLinks,Status} from '../components/shared';

export default function DomainRecords(){
 const[params,setParams]=useSearchParams();const classId=params.get('class')||'DefectOccurrence';
 const[query,setQuery]=useState('');const[offset,setOffset]=useState(0);
 const{data:schema,error:schemaError}=useQuery({queryKey:['shared-schema'],queryFn:()=>api('/ontology/schema')});
 const{data,error}=useQuery({queryKey:['report-records',classId,query,offset],queryFn:()=>api('/domain/classes/'+classId+'/records?q='+encodeURIComponent(query)+'&offset='+offset)});
 return <section className="page-pad domain-records"><h2>Report records</h2>
  <Notice>These are instances extracted from reports. Identifiers and source wording belong here. Automatic document mappings require review; this is not a validated model of the physical building.</Notice>
  <div className="graph-entry-controls"><label>Record class<select aria-label="Record class" value={classId} onChange={e=>{setParams({view:'records',class:e.target.value});setOffset(0);setQuery('')}}>{schema?.classes.map((c:Row)=><option key={c.id} value={c.id}>{c.label}</option>)}</select></label><label>Search report records<input aria-label="Search report records" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0)}} placeholder="Identifier, source wording or location…"/></label></div>
  <p><Link to={'/ontology?class='+classId}>Inspect the shared class definition ↗</Link></p><ErrorBox error={error||schemaError}/>
  {data?<><p>{data.total} records · showing {data.items.length?offset+1:0}–{offset+data.items.length}</p><div className="domain-record-grid">{data.items.map((r:Row)=><article className="domain-record" key={r.id}><h3>{r.label}</h3><div className="predicate-list"><Status value={r.class_id}/><Status value={r.statement_kind}/><Status value={r.review_state}/>{r.reference_verification!=='not_applicable'?<Status value={r.reference_verification}/>:null}{r.repair_outcome!=='not_applicable'?<Status value={r.repair_outcome}/>:null}</div><p className="record-excerpt">{String(r.properties.recorded_text||r.properties.work_scope||r.properties.recorded_location||r.properties.role_name||'Document evidence record').slice(0,500)}</p><Link className="button" to={'/knowledge-graph?entity='+encodeURIComponent(r.id)}>Explore this report record ↗</Link><SourceLinks ids={r.anchor_ids}/>{!r.anchor_ids.length?<small>Evidence: original report structure / preserved asset</small>:null}</article>)}</div>{!data.total?<Notice>No published records of this class. A source topic or keyword alone cannot establish a physical entity.</Notice>:null}<div className="form-row"><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>Previous records</button><button disabled={data.next_offset===null} onClick={()=>setOffset(data.next_offset)}>Next records</button></div></>:<p>Loading report records…</p>}
 </section>
}

export function SearchVocabulary(){
 const{data,error}=useQuery({queryKey:['search-vocabulary'],queryFn:()=>api('/search-vocabulary')});
 return <section className="page-pad"><h2>Search words and aliases</h2><Notice>These terms help find passages. Matching a word does not identify a physical element, diagnose a defect or establish a building class.</Notice><ErrorBox error={error}/><div className="concept-cards">{data?.items.map((c:Row)=><article className="concept-card" key={c.id}><strong>{c.label}</strong><small>Search family: {c.family.replace(/([a-z])([A-Z])/g,'$1 $2')}</small><p>{c.definition}</p><small>Aliases: {c.aliases.join(', ')}</small></article>)}</div></section>
}
