'use strict';
const icons = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  inbox:'<path d="M4 5h16l2 10v4H2v-4z"/><path d="M3 14h5l2 3h4l2-3h5"/>',
  list:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m6 9 1 1 2-3m2 2h6m-11 5 1 1 2-3m2 2h6"/>',
  history:'<path d="M3 10a9 9 0 1 1 1.3 7m-1.6-7 .4-5m-.4 5h5M12 7v5l4 2"/>',
  panels:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  play:'<path d="m7 4 12 8-12 8z"/>',calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v5m10-5v5M3 11h18"/>',
  timer:'<circle cx="12" cy="14" r="7.5"/><path d="M9 2h6m-3 0v4m4.7.9 1.8-2M12 14l3-3"/>',
  box:'<path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5m-9 5v10m-5-17 9 5"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  spark:'<path d="m12 3 1.8 6.2L20 11l-6.2 1.8L12 19l-1.8-6.2L4 11l6.2-1.8zM19 2v4m-2-2h4"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  book:'<path d="M4 5c3-1 6-1 8 1 2-2 5-2 8-1v14c-3-1-6-1-8 1-2-2-5-2-8-1zM12 6v14"/>',
  truck:'<path d="M2 5h12v12H2zM14 9h4l4 5v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
  shield:'<path d="m12 3 8 3v6c0 5-4 8-8 10-4-2-8-5-8-10V6z"/><path d="m8 12 3 3 5-6"/>',
  bulb:'<path d="M8.5 16c0-2.5-3-3.4-3-7a6.5 6.5 0 0 1 13 0c0 3.6-3 4.5-3 7M9 17h6m-6 3h6"/>',
  plane:'<path d="m2 12 8 1 7-8c1.5-1.5 3.5-1 3 1l-5 11-2 3-2-5-5 2z"/>',
  check:'<path d="m5 12 4 4L19 6"/>',mail:'<rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="m3 6 9 7 9-7"/>',
  x:'<path d="m6 6 12 12M18 6 6 18"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9h.01"/>'
};
const icon=name=>'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">'+icons[name]+'</svg>';
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
const replayStart = Date.parse('2026-11-21T20:44:00+01:00');
const launch = Date.parse('2026-11-22T20:00:00+01:00');
const logPrefix = 'manti-demo.decision.';
const stateKey = 'manti-demo.session';
const verbs = {approve:'Approve', decline:'Decline', negotiate:'Negotiate'};
const outcomes = {approve:'Approved', decline:'Declined', negotiate:'Negotiation requested'};
const baseline = editions.map(e => e.median);
const number = value => value.toLocaleString('en-US');
const euros = new Intl.NumberFormat('en-IE', {style:'currency',currency:'EUR',notation:'compact',maximumFractionDigits:2});
const formatTime = new Intl.DateTimeFormat('en-GB', {timeZone:'Europe/Berlin',weekday:'short',hour:'2-digit',minute:'2-digit'});
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const content = document.querySelector('#content');
const dialog = document.querySelector('#dialog');
const dialogContent = document.querySelector('#dialog-content');
let productId = 'books';
let selectedOffer = products.books.offers[0].key;
let activeRecordId = null;
let records = [];
let started = Date.now();
let forecast = [...baseline];
let reviewer = '';
let currentDraft = null;
const isArchive = () => location.hash === '#activity';
const now = () => replayStart + Math.max(0, Date.now()-started);
const validForecast = values => Array.isArray(values) && values.length === editions.length && values.every(n => Number.isSafeInteger(n) && n >= 0);
function readRecords(){
  const saved = [];
  try {
    for(const key of Object.keys(localStorage).filter(k => k.startsWith(logPrefix))){
      const r = JSON.parse(localStorage.getItem(key));
      if(products[r.product]?.offers.some(o => o.key === r.offer) && Object.hasOwn(verbs,r.action) && validForecast(r.forecast)) saved.push(r);
    }
    records = saved.sort((a,b) => b.at-a.at);
  } catch {}
}
try {
  const state = JSON.parse(sessionStorage.getItem(stateKey));
  if(state){
    if(validForecast(state.forecast)) forecast = state.forecast;
    if(Number.isFinite(state.started)) started = state.started;
    reviewer = state.reviewer || '';
  }
} catch {}
function saveSession(){
  try { sessionStorage.setItem(stateKey, JSON.stringify({started,forecast,reviewer})); } catch {}
}
readRecords();
saveSession();
const archivedRecord = () => records.find(r => r.id === activeRecordId);
const title = (name,heading,aside='') => '<div class="card-heading"><h2 class="card-title">'+icon(name)+heading+'</h2>'+aside+'</div>';
function statCards(values){
  const metrics = editions.map((e,i) => {
    const expected = values[i];
    const gap = Math.max(0,e.target-expected);
    const percent = Math.min(100,expected*100/e.target);
    const exposure = gap*e.unitLoss;
    const lossLabel = i===0 ? 'Refund exposure' : 'Potential loss¹';
    return `<article class="stat edition ${gap?'short':'complete'}">
      <h2 class="stat-label"><span class="chip-icon">${icon(e.icon)}</span>${e.name}</h2>
      <div class="metric"><strong>${number(gap)}</strong><span>${gap?'boxes short':'short · target met'}</span></div>
      <div class="progress-wrap"><div class="track"><span style="width:${percent}%"></span></div>
      <div class="progress-caption"><span>${number(expected)} / ${number(e.target)}</span><b>${Number(percent.toFixed(1))}%</b></div></div>
      <div class="loss"><span>${lossLabel}</span><b title="€${number(exposure)}">${euros.format(exposure)}</b></div>
    </article>`;
  }).join('');
  return `<section class="stats" aria-label="Launch forecast"><article class="stat countdown"><canvas aria-hidden="true"></canvas>
    <h2 class="stat-label"><span class="chip-icon">${icon('timer')}</span>${isArchive()?'Time left at snapshot':'Time to launch'}</h2>
    <div class="clock-readout" role="timer">${['Hours','Min','Sec'].map((u,i)=>(i?'<em>:</em>':'')+'<div><b id="clock-'+i+'">00</b><small>'+u.toUpperCase()+'</small></div>').join('')}</div>
    <div class="cutoff">Sun, 22 Nov · 20:00 CET</div></article>${metrics}</section>`;
}
function tick(){
  const at = isArchive() ? archivedRecord()?.at ?? replayStart : now();
  const seconds = Math.max(0,Math.ceil((launch-at)/1000));
  [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].forEach((n,i)=>{
    const el=document.getElementById('clock-'+i);
    if(el) el.textContent=String(n).padStart(2,'0');
  });
}
function tabs(){
  return '<div class="tabs" role="tablist" aria-label="Products">'+Object.entries(products).map(([id,p])=>
    `<button role="tab" id="tab-${id}" aria-controls="product-panel" tabindex="${id===productId?0:-1}" aria-selected="${id===productId}" data-product="${id}">${p.tab}</button>`).join('')+'</div>';
}
function emailRows(){
  const offers = products[productId].offers;
  return offers.map(o=>{
    const e=emailEvidence[o.key];
    const initials=e.supplier.split(' ').slice(0,2).map(word=>word[0]).join('');
    const pick=offers.length>1&&!isArchive();
    const body=`<span class="vendor-avatar">${esc(initials)}</span><span class="offer-info"><strong>${esc(e.supplier)}</strong><span>${o.detail}</span></span>`;
    return `<div class="offer-row ${selectedOffer===o.key?'picked':''}">${pick?`<button class="offer-pick" aria-pressed="${selectedOffer===o.key}" data-select="${o.key}"><span class="radio-dot"></span>${body}</button>`:body}
      <button class="email-button" data-mail="${o.key}" aria-label="Read email from ${esc(e.supplier)}" title="Read supplier email">${icon('mail')}</button></div>`;
  }).join('');
}
function offerCard(){
  const p=products[productId], r=archivedRecord();
  let panel;
  if(isArchive()){
    panel=r?`<div class="recommend"><div class="rec-label">${icon('history')}Recorded decision</div><h3>${outcomes[r.action]} · ${esc(emailEvidence[r.offer].supplier)}</h3>
      <p>${esc(r.by)} · ${formatTime.format(r.at)} CET</p><button class="quiet" data-saved="${esc(r.id)}">${icon('mail')}Read saved draft</button></div>`:
      '<div class="recommend"><h3>No decisions recorded for this product</h3><p>Decisions appear here when a reviewer saves an email draft on the dashboard.</p></div>';
  } else {
    const e=emailEvidence[selectedOffer];
    panel=`<div class="recommend"><div class="rec-top"><div class="rec-label">${icon('spark')}Recommended choice</div><span class="rec-due">${icon('clock')}${p.due}</span></div>
      <h3>${p.title}</h3><p>${p.why}</p><div class="rec-cost"><b>${p.value}</b><small>${p.valueLabel}</small></div></div>`;
    return '<section class="card offers-card">'+title('inbox','Supplier offers')+tabs()+
      `<div role="tabpanel" id="product-panel" aria-labelledby="tab-${productId}">${panel}<div class="offers-heading"><b>Supplier emails</b><small>${p.offers.length} ${p.offers.length===1?'thread':'threads'}</small></div>${emailRows()}
      <div class="decision-bar"><div class="decision-label">Reply to <b>${esc(e.supplier)}</b></div><div class="decision-buttons">${Object.entries(verbs).map(([k,v])=>`<button class="${k==='approve'?'btn':'outline-btn'}" data-action="${k}">${v}</button>`).join('')}</div></div></div></section>`;
  }
  return '<section class="card offers-card">'+title('inbox','Supplier decisions')+tabs()+`<div role="tabpanel" id="product-panel" aria-labelledby="tab-${productId}">${panel}<div class="offers-heading"><b>Supplier emails</b></div>${emailRows()}</div></section>`;
}
function deadlineCard(){
  return '<section class="card">'+title('clock','Decision deadlines','<span class="small-count">'+orderedTasks.length+'</span>')+
    '<div class="deadline-list" role="region" aria-label="Decision deadlines" tabindex="0">'+orderedTasks.map(id=>{
      const p=products[id];
      return `<button class="deadline-item" data-task="${id}"><span class="deadline-icon ${p.tone}">${icon(p.icon)}</span><span class="deadline-copy"><b>${p.queue}</b><small>${p.short}</small></span><span class="due">${p.due}</span></button>`;
    }).join('')+'</div></section>';
}
function historyCard(){
  return '<section class="card">'+title('history','Decision history','<span class="small-count">'+records.length+'</span>')+
    '<div class="deadline-list" role="region" aria-label="Decision history" tabindex="0">'+records.map(r=>
    `<button class="deadline-item" data-record="${esc(r.id)}" aria-pressed="${activeRecordId===r.id}"><span class="deadline-icon">${icon(products[r.product].icon)}</span><span class="deadline-copy"><b>${products[r.product].tab} · ${outcomes[r.action]}</b><small>${esc(r.by)} · ${esc(emailEvidence[r.offer].supplier)}</small></span><span class="due">${formatTime.format(r.at)}</span></button>`).join('')+
    (records.length?'':'<p class="empty">No saved decisions yet.</p>')+'</div></section>';
}
function insightCard(){
  const r=archivedRecord(), p=products[productId];
  const h=isArchive()?'Decision context':'Actionable insight';
  const label=isArchive()?p.queue:'Protect Collector’s boxes first';
  const description=isArchive()?(r?p.timing:'Select a recorded decision to see its planning window.'):'Each missed preorder means a €120 refund. Prioritize scarce game cards for Collector’s and pair the art-book delivery with a statue inspection.';
  return '<section class="card insight">'+title('bulb',h)+'<h3>'+label+'</h3><p>'+description+'</p></section>';
}
function render(){
  const archived=isArchive(), r=archivedRecord();
  const values=archived?(r?.forecast??baseline):forecast;
  const heading=archived?'Activity Log':'Dashboard';
  document.querySelector('#view-title').textContent=heading;
  document.querySelector('#view-subtitle').textContent=archived?'Grand Heist 6 · Forecast and supplier decisions at the time of review':'Grand Heist 6 · Hamburg distribution center';
  document.title=heading+' · Manti';
  document.querySelectorAll('[data-nav]').forEach(a=>{
    if(a.dataset.nav===(archived?'activity':'overview')) a.setAttribute('aria-current','page');
    else a.removeAttribute('aria-current');
  });
  content.classList.toggle('archived',archived);
  content.innerHTML=statCards(values)+'<div class="forecast-note"><span>¹ Standard assumes €32 per late box. Actual loss is unconfirmed.</span>'+
    (!archived?'<button data-forecast class="quiet">'+icon('info')+(values.some((v,i)=>v!==baseline[i])?'Edit forecast scenario':'Forecast details')+'</button>':'')+'</div>'+
    '<div class="body-grid">'+offerCard()+'<div class="side-stack">'+(archived?historyCard():deadlineCard())+insightCard()+'</div></div>'+
    '<footer class="forecast-foot">Forecast · Sat 19:25 CET &nbsp;·&nbsp; Email replay · Sat 20:44 CET</footer>';
  tick();
  drawLaunchCargo(content.querySelector('canvas'));
}
function selectRecord(r){
  if(!r){activeRecordId=null; return;}
  activeRecordId=r.id;productId=r.product;selectedOffer=r.offer;
}
function selectProduct(id){
  productId=id; selectedOffer=products[id].offers[0].key;
  if(isArchive()) selectRecord(records.find(r=>r.product===id));
  render();
  document.getElementById('tab-'+id).focus({preventScroll:true});
}
function openDialog(markup){
  dialogContent.innerHTML=markup;
  dialog.setAttribute('aria-labelledby','dialog-title');
  if(!dialog.open) dialog.showModal();
}
function emailDialog(key){
  const e=emailEvidence[key], o=products[productId].offers.find(o=>o.key===key);
  openDialog(`<div class="overline">Supplier email</div><h2 id="dialog-title">${esc(e.supplier)}</h2><p class="mini">Sat 21 Nov · ${e.time} CET</p><p class="mail-summary">${o.summary}</p>
    <details class="original"><summary>Original email excerpt</summary><p>${esc(e.excerpt)}</p></details><dl><dt>Subject</dt><dd>${esc(e.subject)}</dd><dt>Thread</dt><dd>${e.thread}</dd></dl>`);
}
function editDraft(action){
  const e=emailEvidence[selectedOffer];
  currentDraft={product:productId,offer:selectedOffer,action};
  const body=`Hello ${e.supplier} team,\n\n${replyTerms[selectedOffer][action]}\n\nBest regards,\nSoony launch team`;
  openDialog(`<div class="overline">${products[productId].tab} · ${verbs[action]}</div><h2 id="dialog-title">Review email draft</h2>
    <p class="modal-p">Save your decision, then open the draft in your email app to send it yourself.</p>
    <form id="draft-form" class="editor"><div class="to-line">To <strong>${esc(e.supplier)}</strong><small>${esc(e.recipient)}</small></div>
    <label>Subject<input name="subject" maxlength="350" required value="${esc(e.subject)}"></label>
    <label>Message<textarea name="body" rows="7" required>${esc(body)}</textarea></label>
    <label>Decision made by<input name="by" autocomplete="name" maxlength="80" placeholder="Your name" required value="${esc(reviewer)}"></label>
    <button type="submit" class="btn">Save decision &amp; draft</button></form>`);
}
function savedDraft(r){
  const e=emailEvidence[r.offer];
  const url='mailto:'+e.recipient+'?subject='+encodeURIComponent(r.subject)+'&body='+encodeURIComponent(r.body);
  openDialog(`<div class="overline">Saved draft · ${outcomes[r.action]}</div><h2 id="dialog-title">${esc(e.supplier)}</h2><p class="mini">${esc(r.by)} · ${formatTime.format(r.at)} CET</p>
    <dl><dt>To</dt><dd>${esc(e.recipient)}</dd><dt>Subject</dt><dd>${esc(r.subject)}</dd></dl><p class="mail-summary draft-body">${esc(r.body)}</p>
    <div class="dialog-actions"><button class="outline-btn" data-close>Close</button><a href="${esc(url)}" class="btn">${icon('mail')}Open in email app</a></div>`);
}
function forecastDialog(){
  openDialog(`<div class="overline">Forecast scenario</div><h2 id="dialog-title">Expected boxes at launch</h2><p class="modal-p">The baseline is the median of 500 simulations. Change expected box counts to preview shortages and financial exposure.</p>
    <form class="editor" id="forecast-form">${editions.map((e,i)=>`<label>${e.name} · target ${number(e.target)}<input type="number" name="edition${i}" required min="0" max="${e.target}" step="1" value="${forecast[i]}"></label>`).join('')}
    <p class="modal-p">Collector’s exposure uses €120 per missed preorder. Standard uses an unconfirmed €32 per late box. A delayed Standard box can still sell.</p>
    <div class="dialog-actions"><button type="button" class="outline-btn" data-reset>Restore baseline</button><button class="btn" type="submit">Apply scenario</button></div></form>`);
}
dialog.addEventListener('submit',event=>{
  event.preventDefault();
  const form=event.target, data=new FormData(form);
  if(form.id==='forecast-form'){
    forecast=editions.map((_,i)=>Number(data.get('edition'+i)));saveSession();dialog.close();render();return;
  }
  if(form.id!=='draft-form'||!currentDraft) return;
  for(const field of ['by','subject','body']){
    if(!data.get(field).trim()){form.elements[field].value='';form.reportValidity();return;}
  }
  const record={...currentDraft,id:crypto.randomUUID(),at:now(),by:data.get('by').trim(),subject:data.get('subject').trim(),body:data.get('body').trim(),forecast:[...forecast]};
  try { localStorage.setItem(logPrefix+record.id,JSON.stringify(record)); }
  catch { document.querySelector('#draft-form button').textContent='Storage unavailable · retry';return; }
  reviewer=record.by;saveSession();readRecords();currentDraft=null;render();savedDraft(record);
});
document.addEventListener('click',event=>{
  const btn=event.target.closest('button');if(!btn)return;
  const d=btn.dataset;
  if('close' in d){dialog.close();return;}
  if('reset' in d){forecast=[...baseline];saveSession();dialog.close();render();return;}
  if('forecast' in d){forecastDialog();return;}
  if(d.product){selectProduct(d.product);return;}
  if(d.mail){emailDialog(d.mail);return;}
  if(d.select){selectedOffer=d.select;render();content.querySelector('[data-select="'+d.select+'"]').focus({preventScroll:true});return;}
  if(d.action){editDraft(d.action);return;}
  if(d.saved){savedDraft(records.find(r=>r.id===d.saved));return;}
  if(d.record){selectRecord(records.find(r=>r.id===d.record));render();content.querySelector('[data-record="'+d.record+'"]').focus({preventScroll:true});return;}
  if(d.task){
    const p=products[d.task];
    openDialog(`<div class="overline">Decision deadline · ${p.owner}</div><h2 id="dialog-title">${p.queue}</h2><p class="modal-p">${p.timing}</p><div class="dialog-actions"><button class="btn" data-review="${d.task}">Review supplier options</button></div>`);return;
  }
  if(d.review){dialog.close();selectProduct(d.review);}
});
dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
document.addEventListener('keydown',e=>{
  if(!e.target.closest('[role=tab]'))return;
  const ids=Object.keys(products),i=ids.indexOf(productId);
  const next={ArrowLeft:(i+ids.length-1)%ids.length,ArrowRight:(i+1)%ids.length,Home:0,End:ids.length-1}[e.key];
  if(next!==undefined){e.preventDefault();selectProduct(ids[next]);}
});
function navigate(){
  if(dialog.open)dialog.close();
  if(isArchive())selectRecord(records[0]);
  render();
}
window.addEventListener('hashchange',()=>{navigate();document.querySelector('#main').focus();window.scrollTo(0,0);});
window.addEventListener('storage',e=>{if(e.key===null||e.key.startsWith(logPrefix)){readRecords();if(isArchive())render();}});
window.addEventListener('resize',()=>drawLaunchCargo(content.querySelector('canvas')));
navigate();setInterval(tick,1000);
