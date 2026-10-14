import React,{lazy,Suspense,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter,NavLink,Link,Routes,Route,useLocation} from 'react-router-dom';
import {QueryClient,QueryClientProvider,useQuery} from '@tanstack/react-query';
import {Home,BookOpen,FileText,Image,Search,Folder,Library,ClipboardCheck,Settings,Menu,Plus,Network,Shapes} from 'lucide-react';
import {api} from './api/client';
import {Workspace,LibraryPage,Findings,MediaPage,Research,Projects,References,Review,SettingsPage} from './pages';
import './style.css';
const SourceViewer=lazy(()=>import('./viewers/SourceViewer'));
const GraphViewer=lazy(()=>import('./viewers/GraphViewer'));
const KnowledgeGraphPage=lazy(()=>import('./pages/KnowledgeGraphPage'));
const OntologyPage=lazy(()=>import('./pages/OntologyPage'));
const queryClient=new QueryClient({defaultOptions:{queries:{retry:1,staleTime:2000}}});
const nav=[['/','Workspace',Home],['/library','Library',BookOpen],['/findings','Findings',FileText],['/media','Evidence images',Image],['/knowledge-graph','Knowledge graph',Network],['/ontology','Ontology',Shapes],['/research','Research',Search],['/projects','Projects',Folder],['/references','References',Library],['/review','Review queue',ClipboardCheck],['/settings','Settings',Settings]] as const;
function Shell(){
  const[menu,setMenu]=useState(false);const location=useLocation();const {data:health}=useQuery({queryKey:['health'],queryFn:()=>api('/health'),refetchInterval:12000});
  const current=location.pathname.startsWith('/graph/')?nav.find(([p])=>p==='/knowledge-graph'):nav.find(([p])=>p==='/'?location.pathname==='/':location.pathname.startsWith(p));
  return <div className="app-shell"><aside className={menu?'nav open':'nav'}><Link to="/" className="brand">Defect<br/>Intelligence<span className="brand-line"/></Link><nav>{nav.map(([path,label,Icon])=><NavLink to={path} end={path==='/'} key={path} onClick={()=>setMenu(false)}><Icon size={21}/>{label}</NavLink>)}</nav><div className="nav-bottom">Private workspace<small>Source-backed research</small></div></aside><div className="main-shell"><header><button className="mobile-menu" aria-label="Open navigation" onClick={()=>setMenu(!menu)}><Menu/></button><div><h1>{current?.[1]||'Source evidence'}</h1><p>{location.pathname.startsWith('/findings')?'Trace the observation, reasoning and repair back to its source.':'Research with original evidence and inspectable context.'}</p></div><Link className="button primary" to="/research"><Plus size={18}/>New research</Link></header><main><Suspense fallback={<p className="empty">Opening evidence…</p>}><Routes><Route path="/" element={<Workspace/>}/><Route path="/library/:id?" element={<LibraryPage/>}/><Route path="/findings/:id?" element={<Findings/>}/><Route path="/media" element={<MediaPage/>}/><Route path="/media/:id" element={<SourceViewer media/>}/><Route path="/sources/:id" element={<SourceViewer/>}/><Route path="/graph/:id" element={<GraphViewer/>}/><Route path="/knowledge-graph" element={<KnowledgeGraphPage/>}/><Route path="/ontology" element={<OntologyPage/>}/><Route path="/research/:id?" element={<Research/>}/><Route path="/projects/:id?" element={<Projects/>}/><Route path="/references" element={<References/>}/><Route path="/review" element={<Review/>}/><Route path="/settings" element={<SettingsPage/>}/></Routes></Suspense></main><footer><span><i/>{health?.processing||'Checking processing destination'} · Applicability unresolved</span><span>{health?.services?.worker==='ready'?'Worker connected':'Worker offline'} · {health?.services?.checkpoints?.replaceAll('_',' ')||'Checking workspace'}</span></footer></div></div>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={queryClient}><BrowserRouter><Shell/></BrowserRouter></QueryClientProvider></React.StrictMode>);
