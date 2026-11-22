import { EmailBody } from "./EmailBody";
import { ExchangeContext } from "./currency";
import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { dashboardApi, hostedReplayBuild, isStaticMode, type DashboardData, type Source, type SupplierMessage } from "./api";
import { AgentGraph } from "./agents/AgentGraph";
import { UploadData, type UploadResult } from "./UploadData";
import { Offers } from "./suppliers/Offers";
import { ComponentCoverage } from "./desk/ComponentCoverage";
import { Deadlines } from "./desk/Deadlines";
import { Forecast, displayDate } from "./desk/Forecast";
import { Dialog, Icon } from "./desk/UI";
import { MantiLogo } from "./SupplyMap";
import "./desk/reference.css";
import "./desk/connected.css";
import "./desk/header.css";

const pages = [
  {id:"dashboard", label:"Dashboard", icon:"grid"},
  {id:"activity", label:"Activity Log", icon:"history"},
  {id:"agents", label:"Agents", icon:"network"},
  {id:"import", label:"Data import", icon:"upload"},
] as const;
const currentPage = () => pages.find(p=>"#"+p.id===location.hash.split("?")[0]) ?? pages[0];
const threadFromUrl = () => {
  const query = new URLSearchParams(location.search);
  return query.get("thread") || (query.get("mail")==="1" ? "mailbox" : null);
};

function mailKey(message: SupplierMessage) {
  return message.transport?.messageId || [message.side, message.timestamp ?? message.time, message.text.trim()].join("\n");
}

function AccountMenu({user}: {user: string}) {
  const menu = useRef<HTMLDetailsElement>(null);
  const [signingOut, setSigningOut] = useState(false);
  useEffect(() => {
    const dismissOutside = (event: Event) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) menu.current.open = false;
    };
    const dismissOnNavigation = () => { if (menu.current) menu.current.open = false; };
    const restore = () => { setSigningOut(false); dismissOnNavigation(); };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("focusin", dismissOutside);
    window.addEventListener("hashchange", dismissOnNavigation);
    window.addEventListener("pageshow", restore);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("focusin", dismissOutside);
      window.removeEventListener("hashchange", dismissOnNavigation);
      window.removeEventListener("pageshow", restore);
    };
  }, []);
  return <details className="account" ref={menu} onKeyDown={event => {
    if (event.key === "Escape" && menu.current?.open) {
      menu.current.open = false;
      menu.current.querySelector("summary")?.focus();
    }
  }}>
    <summary aria-label={"Account · "+user} title={user}>{user.slice(0,1).toUpperCase()}</summary>
    <form method="post" action="/logout" onSubmit={event => {
      if (signingOut) event.preventDefault();
      else setSigningOut(true);
    }}><span>{user}</span><button className="quiet" disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button></form>
  </details>;
}

function App() {
  const [base,setBase] = useState<DashboardData | null>(null);
  const [imported,setImported] = useState<UploadResult | null>(null);
  const [page,setPage] = useState(currentPage);
  const previousPage = useRef(page.id);
  const [error,setError] = useState("");
  const [retrying,setRetrying] = useState(false);
  const [source,setSource] = useState<Source|null>(null);
  const [threadId,setThreadId] = useState<string|null>(threadFromUrl);
  const [reviewer,setReviewer] = useState(()=>{try{return localStorage.getItem("soony-reviewer")??"";}catch{return "";}});
  const dashboardRequest = useRef(0);
  const refresh = useCallback(async()=>{
    const request = ++dashboardRequest.current;
    try {
      const latest = await dashboardApi.getDashboard();
      if (request === dashboardRequest.current) {setBase(latest);setError("");}
    } catch(e){if (request === dashboardRequest.current) setError(e instanceof Error?e.message:"Launch forecast unavailable.");}
  },[]);
  const showUpload = useCallback((result:UploadResult|null)=>setImported(result),[]);
  async function retry() {
    setRetrying(true);
    try { await refresh(); } finally { setRetrying(false); }
  }
  useEffect(()=>{
    let active = true;
    let timer: number;
    const poll = async () => {
      await refresh();
      if (active && !hostedReplayBuild) timer = window.setTimeout(poll, 5000);
    };
    void poll();
    return ()=>{ active = false; window.clearTimeout(timer); };
  },[refresh]);
  useEffect(()=>{
    const navigate=()=>{setPage(currentPage());setThreadId(threadFromUrl());setSource(null);window.scrollTo(0,0);};
    window.addEventListener("hashchange",navigate);
    window.addEventListener("popstate",navigate);
    return ()=>{window.removeEventListener("hashchange",navigate);window.removeEventListener("popstate",navigate);};
  },[]);
  useEffect(()=>{
    document.title=page.label+" · Manti";
    if (previousPage.current !== page.id) document.getElementById("main")?.focus({preventScroll:true});
    previousPage.current = page.id;
  },[page]);
  const retryButton = <button className="quiet" disabled={retrying} onClick={retry}>{retrying ? "Retrying…" : "Retry"}</button>;
  if(!base)return <main className="loading-screen" role="status"><p>{error||"Loading the launch forecast…"}</p>{error && retryButton}</main>;
  const data=imported?{...imported.dashboard,currentUser:base.currentUser}:base;
  const replay=hostedReplayBuild||isStaticMode()||data.sync?.mailMode==="dry-run";
  const archive=page.id==="activity";
  const home=page.id==="dashboard"||archive;
  const city=data.network?.hub?.name || data.launch.location;
  const locationLabel = data.launch.location.startsWith("DC-") && data.network?.hub?.name ? city+" distribution center" : city;
  const subtitle=page.id==="agents"?"Agent activity":page.id==="import"?"Case files":archive?"Supplier decisions and reviewers":locationLabel;
  const threads=[...(data.mailHistory?.threads??[]),...data.threads];
  const thread=threadId==="mailbox"?threads[0]:threads.find(t=>t.id===threadId);
  // A verified archive copy may predate the reply shown in a current offer.
  const messages = new Map<string, SupplierMessage>();
  for (const copy of threads.filter(t => thread && t.id === thread.id)) {
    for (const message of copy.messages) {
      const key = mailKey(message);
      if (!messages.has(key)) messages.set(key, message);
    }
  }
  const correspondence = [...messages.values()].sort((a,b) => (Date.parse(a.timestamp ?? "") || 0) - (Date.parse(b.timestamp ?? "") || 0));
  const closeThread=()=>{
    setThreadId(null);
    const url=new URL(location.href);
    url.searchParams.delete("mail");url.searchParams.delete("thread");
    if(url.hash.startsWith("#message-"))url.hash="#dashboard";
    history.replaceState(null,"",url);
  };
  const dashboardSidebar=<><ComponentCoverage risks={data.risks}/><Deadlines key={imported?.id??"live"} practiceKey={imported?.id??"workspace"} data={data} practice={!!imported||hostedReplayBuild||isStaticMode()} refresh={refresh} onThread={setThreadId} onEvidence={setSource}/></>;
  const file=source?.source_file??source?.file;
  return <ExchangeContext.Provider value={data.exchangeRates}><a className="skip" href="#main" onClick={event=>{
    event.preventDefault();
    document.getElementById("main")?.focus();
  }}>Skip to main content</a><div className="shell workspace-shell">
    <header className="workspace-header">
      <div className="workspace-header-inner">
        <a href="#dashboard" aria-label="Manti dashboard"><MantiLogo/></a>
        <nav className="workspace-nav" aria-label="Workspace">
          {pages.map(p=><a key={p.id} href={"#"+p.id} aria-current={p.id===page.id?"page":undefined}>
            <Icon name={p.icon}/><span>{p.label}</span>
          </a>)}
        </nav>
        {data.currentUser&&<AccountMenu user={data.currentUser}/>}
      </div>
    </header>
      <main id="main" tabIndex={-1}><header className="page-title"><div><h1>{page.label}</h1><p>{data.launch.name} · {subtitle}{imported?" · Private scenario":replay?" · Demo replay":""}</p></div>
        {data.sync?.time && <span className="date-chip"><Icon name="clock"/>Updated {displayDate(data.sync.time)}</span>}</header>
        {data.sync?.error && <p className="mail-summary" role="status">The last sync failed. Showing the last available forecast.</p>}
        {error&&<p className="mail-summary" role="alert">{error} {retryButton}</p>}
        <div className="desk-tools theme-dark manti-workspace" hidden={page.id!=="import"}>{isStaticMode()?<p>Open the connected workspace to import data.</p>:<UploadData onResult={showUpload}/>}</div>
        {page.id==="agents"&&<div className="desk-tools theme-dark manti-workspace"><AgentGraph key={imported?.id??"workspace"} data={data} scenario={!!imported} stale={!!error} onEvidence={setSource}/></div>}
        {home&&<div id="content" className={archive?"archived":undefined}>
          {!archive&&<Forecast key={imported?.id??"workspace"} data={data}/>}
          <div className="body-grid">{imported?<><section className="card"><h2>{archive?"Supplier decisions":"Supplier offers"}</h2><p className="empty">This private forecast uses your imported files. <a className="quiet" href="#import">Manage import</a></p></section>
            {!archive&&<aside className="side-stack">{dashboardSidebar}</aside>}</>:
            <Offers archive={archive} currentUser={data.currentUser} reviewer={reviewer} onReviewer={value=>{setReviewer(value);try{localStorage.setItem("soony-reviewer",value);}catch{}}} openThread={setThreadId}>{dashboardSidebar}</Offers>}</div>
        </div>}
      </main></div>
    {threadId&&<Dialog title={thread?.supplier??"Supplier email"} label="Email thread" close={closeThread}>
      {thread?<><p className="mini">{thread.subject}</p>{correspondence.map(m=><article className="thread-message" key={thread.id+":"+mailKey(m)}>
        <b>{m.transport?.from??m.sender}</b><small>{m.timestamp?displayDate(m.timestamp):m.time} · {m.transport?.status?.replace(/_/g," ")??thread.status}</small><EmailBody original={m.text} english={m.english} supplierText={m.supplierText} supplierLanguage={m.supplierLanguage}/></article>)}</>:
        <p className="modal-p">This email thread is unavailable in the current workspace.</p>}</Dialog>}
    {source&&<Dialog title={file??"Source evidence"} label="Source evidence" close={()=>setSource(null)}>
      <p className="mini">{source.page?"Page "+source.page:source.row?"Row "+source.row:"Source location"}</p>{source.quote&&<p className="mail-summary">{source.quote}</p>}
      {file&&!imported&&!isStaticMode()&&!hostedReplayBuild&&<a className="quiet" href={"/api/source/"+file.split("/").map(encodeURIComponent).join("/")} target="_blank" rel="noreferrer">Open original source</a>}</Dialog>}
  </ExchangeContext.Provider>;
}
createRoot(document.getElementById("root")!).render(<App/>);
