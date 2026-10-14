import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Link,useSearchParams} from 'react-router-dom';
import {api,Row} from '../api/client';
import {ErrorBox,Notice} from '../components/shared';
import GraphViewer from '../viewers/GraphViewer';
import DomainRecords,{SearchVocabulary} from './DomainRecords';

export default function KnowledgeGraphPage(){
 const[params,setParams]=useSearchParams();const[query,setQuery]=useState('');
 const{data,error}=useQuery({queryKey:['graph-findings'],queryFn:()=>api('/findings?limit=100')});
 const items:Row[]=data?.items||[];
 const filtered=items.filter(f=>`${f.identifier} ${f.title} ${f.location}`.toLowerCase().includes(query.toLowerCase()));
 const selected=params.get('finding')||items[0]?.id;
 const active=items.find(f=>f.id===selected);
 const entity=params.get('entity');
 const view=params.get('view')||'graph';
 const views=<div className="ontology-tabs page-pad"><Link className={'button '+(view==='graph'?'primary':'')} to="/knowledge-graph">Report graph</Link><Link className={'button '+(view==='records'?'primary':'')} to="/knowledge-graph?view=records">Report records</Link><Link className={'button '+(view==='terms'?'primary':'')} to="/knowledge-graph?view=terms">Search words</Link></div>;
 if(view==='records')return <>{views}<DomainRecords/></>;
 if(view==='terms')return <>{views}<SearchVocabulary/></>;
 return <>
  {views}
  <section className="graph-entry page-pad">
   <Notice>This graph contains report-specific records and evidence links. Finding numbers identify records. Automatic semantic mappings are unreviewed; graph connectivity does not establish domain correctness.</Notice>
   <p>Follow source passages and reported assessments. Select an assertion to inspect its supporting evidence.</p>
   <div className="graph-entry-controls">
    <label>Find a graph<input aria-label="Find a graph" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Planter, waterproofing, DS-166…"/></label>
    <label>Finding to explore<select aria-label="Finding to explore" value={entity?'':selected||''} onChange={e=>setParams({finding:e.target.value})}>
     {entity?<option value="">Exploring a domain record</option>:null}
     {active&&!filtered.some(f=>f.id===active.id)?<option value={active.id}>{active.identifier} · {active.title} · {active.location}</option>:null}
     {filtered.map(f=><option key={f.id} value={f.id}>{f.identifier} · {f.title} · {f.location}</option>)}
    </select></label>
   </div>
   {!entity&&active?<p className="graph-current"><strong>{active.title}</strong> · {active.identifier} · {active.location}</p>:null}
   {entity?<p><Link to="/ontology">Inspect the shared schema ↗</Link></p>:null}
   {query&&!filtered.length?<Notice>No findings in this list match. <Link to={'/findings?q='+encodeURIComponent(query)}>Search the report library</Link>.</Notice>:null}
   {data?.next_cursor?<Notice>Showing the first 100 published findings. <Link to="/findings">Browse all findings</Link>.</Notice>:null}
   <ErrorBox error={error}/>
  </section>
  {entity||selected?<GraphViewer key={entity||selected} findingId={entity?undefined:selected} entityId={entity||undefined}/>:<div className="page-pad"><Notice>{data?'Import and publish a report to explore its knowledge graph.':'Loading published findings…'}</Notice></div>}
 </>
}
