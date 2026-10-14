import {useState} from 'react';
import {Link} from 'react-router-dom';
import {Row,asset} from '../api/client';
import {ErrorBox,MediaTiles,Notice} from './shared';

const purposeLabels:Record<string,string>={context:'Section heading and context',observation:'Recorded observations',
 extent:'Extent',status:'Status',result:'Result / opinion',reasoning:'Reasoning',responsibility:'Responsibility',remediation:'Remediation'};

export default function ReportSectionResults({data,error}:{data?:Row;error?:unknown}){
 const[selectedId,setSelectedId]=useState('');
 const sections:Row[]=data?.sections||[];
 const selected=sections.find(section=>section.id===selectedId)||sections[0];
 if(error)return <section className="report-section-results"><h2>Retrieved report sections</h2><ErrorBox error={error}/></section>;
 if(!data)return <section className="report-section-results"><h2>Retrieved report sections</h2><p>Loading original report wording…</p></section>;
 if(!selected)return <section className="report-section-results"><h2>Retrieved report sections</h2><p>No original report sections have been retrieved for this run yet.</p></section>;
 const headingOnly=(part:Row)=>part.purpose==='context'&&part.blocks.length===1&&part.blocks[0].anchor_id===selected.heading_anchor_id;
 return <section className="report-section-results" aria-label="Retrieved report sections">
  <h2>Retrieved report sections</h2>
  <p className="muted">Original wording from the source report, with the surrounding section kept together. References and opinions retain the report author’s attribution.</p>
  {sections.length>1?<label>Report section<select aria-label="Report section" value={selected.id} onChange={e=>setSelectedId(e.target.value)}>{sections.map(section=><option key={section.id} value={section.id}>{section.title} · {section.filename}</option>)}</select></label>:null}
  <article className="original-report-section" key={selected.id}>
   <header className="original-section-heading"><div><small>{selected.filename}</small><h3>{selected.title}</h3><span className="source-wording-label">Original report wording</span></div><a href={asset(selected.asset_id)} target="_blank" rel="noreferrer">Open original report ↗</a></header>
   {selected.heading_anchor_id?<Link className="section-source-link" to={'/sources/'+selected.heading_anchor_id}>Section heading source ↗</Link>:null}
   <nav className="report-section-contents" aria-label="Original section contents">{selected.parts.filter((part:Row)=>!headingOnly(part)).map((part:Row)=><a key={part.id} href={'#original-'+part.id}>{part.finding?part.finding.identifier:part.option_id?`Remediation ${selected.parts.filter((p:Row)=>p.option_id).findIndex((p:Row)=>p.id===part.id)+1}`:purposeLabels[part.purpose]||part.purpose}</a>)}</nav>
   {selected.parts.filter((part:Row)=>!headingOnly(part)).map((part:Row)=><section className="original-report-subsection" id={'original-'+part.id} key={part.id}>
    <h4>{part.finding?`${part.finding.identifier} · ${part.finding.location}`:purposeLabels[part.purpose]||part.purpose}<small>{part.finding?'Occurrence-specific source':'Shared report section'}</small></h4>
    {part.blocks.map((block:Row)=><div className="original-report-block" key={block.id} data-anchor-id={block.anchor_id}>
     {block.text?<p className={'original-report-text '+(block.kind==='heading'?'original-heading-text':'')}>{block.text}</p>:null}
     {block.media.length?<MediaTiles items={block.media}/>:null}
     <Link className="paragraph-source-link" to={'/sources/'+block.anchor_id}>Source ↗</Link>
    </div>)}
   </section>)}
  </article>
  {data.warnings?.map((warning:string)=><Notice key={warning}>{warning}</Notice>)}
 </section>;
}
