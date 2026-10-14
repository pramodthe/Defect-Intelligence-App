import {useEffect,useMemo,useRef,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Link,useSearchParams} from 'react-router-dom';
import cytoscape from 'cytoscape';
import {api,Row} from '../api/client';
import {ErrorBox,Notice} from '../components/shared';

const readable=(value:string)=>value.replaceAll('_',' ').replace(/([a-z])([A-Z])/g,'$1 $2');
export default function OntologyPage(){
 const{data,error}=useQuery({queryKey:['shared-schema'],queryFn:()=>api('/ontology/schema')});
 const[params,setParams]=useSearchParams();const[query,setQuery]=useState('');const[group,setGroup]=useState('');

 const canvas=useRef<HTMLDivElement>(null);const graph=useRef<cytoscape.Core|null>(null);
 const selectedId=params.get('class')||'DefectOccurrence';
 const classes:Row[]=data?.classes||[];const selected=classes.find(c=>c.id===selectedId);

 const relations:Row[]=data?.relationships||[];
 const related=relations.filter(r=>r.domains.includes(selectedId)||r.ranges.includes(selectedId));
 const visible=useMemo(()=>{
  const ids=new Set<string>([selectedId]);
  for(const r of data?.relationships||[]){if(r.domains.includes(selectedId))r.ranges.forEach((id:string)=>ids.add(id));if(r.ranges.includes(selectedId))r.domains.forEach((id:string)=>ids.add(id))}
  const parent=data?.classes.find((c:Row)=>c.id===selectedId)?.parent;if(parent)ids.add(parent);
  for(const c of data?.classes||[])if(c.parent===selectedId)ids.add(c.id);
  return (data?.classes||[]).filter((c:Row)=>ids.has(c.id));
 },[data,selectedId]);
 useEffect(()=>{
  if(!data||!canvas.current)return;
  const ids=new Set(visible.map((c:Row)=>c.id));const neighbors=visible.filter((c:Row)=>c.id!==selectedId);
  const elements:cytoscape.ElementDefinition[]=visible.map((c:Row)=>{const index=neighbors.findIndex((n:Row)=>n.id===c.id);const angle=-Math.PI/2+index*2*Math.PI/Math.max(1,neighbors.length);return {data:{id:c.id,label:c.label,selected:c.id===selectedId?'yes':'no'},position:c.id===selectedId?{x:400,y:250}:{x:400+300*Math.cos(angle),y:250+180*Math.sin(angle)}}});
  visible.forEach((c:Row)=>{if(ids.has(c.parent)&&(c.id===selectedId||c.parent===selectedId))elements.push({data:{id:'parent:'+c.id,source:c.id,target:c.parent,label:'subclass of'}})});
  data.relationships.forEach((r:Row)=>{for(const source of r.domains)for(const target of r.ranges)if(ids.has(source)&&ids.has(target)&&(source===selectedId||target===selectedId))elements.push({data:{id:r.id+source+target,source,target,label:r.label}})});
  const cy=cytoscape({container:canvas.current,elements,layout:{name:'preset',padding:45},style:[
   {selector:'node',style:{label:'data(label)','background-color':'#16867c',color:'#142b42','font-size':16,'text-wrap':'wrap','text-max-width':'145px','text-valign':'bottom','text-margin-y':8,width:24,height:24}},
   {selector:'node[selected="yes"]',style:{'background-color':'#8064ab','border-color':'#13283e','border-width':3,width:34,height:34}},
   {selector:'edge',style:{label:'data(label)','font-size':11,'text-background-color':'#fff','text-background-opacity':0.8,width:1.4,'line-color':'#bdcbd5','curve-style':'bezier','target-arrow-shape':'triangle','target-arrow-color':'#bdcbd5'}}]});
  graph.current=cy;cy.on('tap','node',event=>choose(event.target.id()));
  const observer=new ResizeObserver(()=>{cy.resize();cy.fit(undefined,50)});observer.observe(canvas.current);
  return()=>{observer.disconnect();cy.destroy();graph.current=null};
 },[data,selectedId,visible]);
 function choose(id:string){setParams({class:id})}
 const filtered=classes.filter(c=>(!group||c.group===group)&&`${c.label} ${c.definition}`.toLowerCase().includes(query.toLowerCase()));
 return <div className="page-pad ontology-page">
  <p>Shared schema for every report: class definitions, properties and permitted relationships. Individual findings and their identifiers belong to report data.</p>
  <ErrorBox error={error}/>
  {data?<>
   <div className="ontology-summary"><span><strong>{classes.length}</strong> domain classes</span><span><strong>{relations.length}</strong> typed relationships</span><span><strong>{data.source_coverage.length}</strong> specification sections</span></div>
   <Notice>Draft schema — domain correctness has not been established. Class counts and software tests do not validate its meaning. Report data is available separately in the <Link to="/knowledge-graph?view=records">knowledge graph record browser</Link>.</Notice>
   <div className="layer-guide"><strong>Schema</strong><span>Defect Occurrence is a class.</span><span>Recorded identifier is a property.</span><span>A finding number is a value on a report record; it is never a class.</span><Link to="/knowledge-graph?view=terms">Search words and aliases ↗</Link></div>
    <div className="graph-entry-controls"><label>Inspect a domain class<select aria-label="Inspect a domain class" value={selectedId} onChange={e=>choose(e.target.value)}>{classes.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select></label><div><strong>{selected?.group}</strong><p>{selected?.definition}</p></div></div>
    <div className="ontology-layout"><section><div className="form-row"><h2>Class relationships</h2><button onClick={()=>graph.current?.fit(undefined,50)}>Fit ontology</button></div><div className="ontology-canvas" ref={canvas} role="img" aria-label="Domain class relationship graph"/><small>Purple: selected class · Teal: related classes. Arrows define permitted relationships, with source and scope required for report instances.</small></section><aside className="ontology-inspector"><h2>{selected?.label}</h2><dl><dt>Parent class</dt><dd>{selected?.parent?<button className="text-button" onClick={()=>choose(selected.parent)}>{readable(selected.parent)}</button>:'Root class'}</dd><dt>Class properties</dt><dd>{selected?.properties.map((p:string)=><span className="status" key={p}>{readable(p)}</span>)}</dd><dt>Specification section</dt><dd>{selected?.source_section}</dd></dl><Link className="button" to={'/knowledge-graph?view=records&class='+selectedId}>Browse records of this class ↗</Link></aside></div>
     <section><h2>Relationships for {selected?.label}</h2><div className="domain-relation-list">{related.map(r=><article key={r.id}><strong>{r.label}</strong><p>{r.definition}</p><small>{r.domains.map(readable).join(' / ')} → {r.ranges.map(readable).join(' / ')}</small><small>Source, scope and independent evidence statuses required</small></article>)}</div></section>
     <section className="ontology-catalog"><h2>Shared class catalog</h2><div className="graph-entry-controls"><label>Search domain classes<input aria-label="Search domain classes" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Assessments, editions, repair, images…"/></label><label>Domain group<select aria-label="Domain group" value={group} onChange={e=>setGroup(e.target.value)}><option value="">All domain groups</option>{data.groups.map((g:string)=><option key={g} value={g}>{g}</option>)}</select></label></div><p>{filtered.length} of {classes.length} classes</p><div className="concept-cards">{filtered.map(c=><button className={'concept-card '+(c.id===selectedId?'selected':'')} key={c.id} onClick={()=>{choose(c.id);window.scrollTo({top:0,behavior:'smooth'})}}><strong>{c.label}</strong><small>{c.group}</small><p>{c.definition}</p></button>)}</div></section>
     <details><summary>Evidence statuses and validation rules</summary><div className="domain-relation-list">{Object.entries(data.status_dimensions).map(([name,values])=><article key={name}><strong>{readable(name)}</strong><p>{(values as string[]).map(readable).join(' · ')}</p></article>)}</div>{data.constraints.map((c:Row)=><p key={c.id}>{c.rule}</p>)}</details>
     <details><summary>Coverage of all {data.source_coverage.length} sections in ONTOLOGY.md</summary>{data.source_coverage.map((c:Row)=><p key={c.section}><strong>{c.section}</strong><br/>{c.covered_by.map(readable).join(', ')}</p>)}<small>Schema version {data.version} · Specification fingerprint {data.source_sha256.slice(0,12)}</small></details>
  </>:<p>Loading the domain model…</p>}
 </div>
}
