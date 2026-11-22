'use strict';
const icons = {
  brand:'<path fill="#b99aff" stroke="none" d="m12 .8 10.8 5.8L12 12.5 1.2 6.6z"/><path fill="#9574d4" stroke="none" d="M1.2 9.2 10.8 14.4v8.8l-9.6-5.4z"/><path fill="#d5c0ff" stroke="none" d="m13.2 14.4 9.6-5.2v8.6l-9.6 5.4z"/>',
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
const products = {
  books:{tab:'Art books',icon:'book',tone:'',title:'Reserve 5,900 art books',why:'Karton Nowak can cover the full art-book gap. Confirm the Hamburg delivery slot before placing the order.',value:'€12,390',valueLabel:'5,900 × €2.10 per book',button:'Approve reservation',done:'Reservation approved',owner:'Buyer',due:'Sun ~06:00',timing:'Target Sun 22 Nov around 06:00 CET at the latest. The 24-hour offer expires Sunday morning. Its exact expiry is unconfirmed.',scope:'Approve a free, provisional hold. The buyer still needs to confirm the purchase order and delivery slot.',queue:'Reserve art books',short:'5,900 books · Collector’s',offers:[
    {key:'kartonBooks',detail:'5,900 available at €2.10 each',summary:'Karton can hold 5,900 finished art books free of charge. The €2.10 unit price is valid for 24 hours from the morning offer. Loading takes up to four hours after a formal order. Warta Trans still needs to confirm the delivery window.'}
  ]},
  cards:{tab:'Game cards',icon:'plane',tone:'blue',title:'Secure the 28,000-card handover',why:'Hwaseong’s air lot is already in transit. Get a timed Frankfurt arrival and reserve customs clearance and the Hamburg dock before it lands.',value:'6,800 cards',valueLabel:'Still short after the air lot arrives',button:'Assign to logistics',done:'Assigned to logistics',owner:'Logistics',due:'Tonight',timing:'Start Saturday evening, before the air lot lands. The carrier has yet to confirm a timed arrival.',scope:'Assign Logistics to obtain the flight ETA, customs documents and a timed Hamburg handover.',queue:'Secure card handover',short:'28,000 cards · Both editions',offers:[
    {key:'hwaseong',detail:'28,000 in transit · handover unconfirmed',summary:'The 28,000-card lot departed Incheon for Frankfurt. The carrier has yet to confirm an arrival time. The remaining 20,000 are expected in Hamburg on 24 November.'},
    {key:'boise',detail:'36,000 at origin · after launch',summary:'Boise has 36,000 cards packed at its dock. Even premium freight cannot deliver the missing 6,800 in time. A written EXW confirmation or a nominated forwarder is required for release.'}
  ]},
  statues:{tab:'Statues',icon:'shield',tone:'',title:'Request a sort of the held statues',why:'Neither supplier can deliver by launch. Ask Quality to inspect the 5,600 units already in Hamburg and release the pieces that pass.',value:'3,400 statues',valueLabel:'Needed for Collector’s boxes',button:'Request quality review',done:'Quality review requested',owner:'Quality & Compliance',due:'Before Sun shift',timing:'Planning target before the Sunday 06:00 pack-out shift. Inspection time and release quantity are unconfirmed.',scope:'Request a full inspection. Quality & Compliance decides which pieces can be released for packing.',queue:'Request statue inspection',short:'3,400 statues · Collector’s',offers:[
    {key:'pune',detail:'5,000 by sea · 28 Nov',summary:'Pune cannot supply 3,400 statues in Hamburg by cutoff. Its next 5,000 units are due by sea on 28 November.'},
    {key:'dongguan',detail:'10,000 by sea · 27 Nov',summary:'Dongguan cannot deliver the missing 3,400 by cutoff. Its next sea shipment of 10,000 pieces is due in Hamburg on 27 November.'}
  ]},
  sleeves:{tab:'Sleeves',icon:'truck',tone:'warm',title:'Verify the revision C sleeve delivery',why:'Karton’s truck should cover the 6,000-sleeve gap for Standard. Check the signed receipt and revision before counting the stock.',value:'20,000 sleeves',valueLabel:'Already ordered from Karton Nowak',button:'Request receipt check',done:'Receipt check requested',owner:'Hamburg warehouse',due:'Tonight',timing:'Check the Hamburg receipt on Saturday evening, when Warta Trans is due at the warehouse.',scope:'Ask the warehouse to confirm the revision, quantity and signed receipt for the existing shipment.',queue:'Verify sleeve receipt',short:'20,000 sleeves · Standard',offers:[
    {key:'kartonSleeves',detail:'20,000 rev C · receipt pending',summary:'Warta Trans was due to deliver 20,000 revision C sleeves on Saturday evening. Karton has yet to receive signed proof of delivery. Additional digital production takes at least 36 hours.'},
    {key:'packright',detail:'No revision C stock for launch',summary:'PackRight has no released revision C sleeves for Sunday. Its revision B stock cannot be used for this launch.'}
  ]}
};
const orderedTasks=['cards','sleeves','books','statues'];
const editions=[{name:'Collector’s Edition',target:72000,median:62550,icon:'layers',cls:'collector'},{name:'Standard Edition',target:640000,median:614650,icon:'box',cls:'standard'}];
const views={overview:['Launch overview','Grand Heist 6 · Hamburg distribution center'],offers:['Supplier offers','Compare the replies for each product and choose the next action.'],decisions:['Decision queue','Open decisions, responsible teams and planning deadlines in Hamburg time.'],activity:['Activity log','Decisions recorded in this demo replay.']};
const replayTime=Date.parse('2026-11-21T20:02:00+01:00'), cutoff=Date.parse('2026-11-22T20:00:00+01:00');
const stateKey='lio-launch-desk-replay-v1';
let selected='books', actions={}, started=Date.now();
try {
  const saved=JSON.parse(sessionStorage.getItem(stateKey));
  if(saved && Number.isFinite(saved.started) && saved.actions && typeof saved.actions==='object'){
    started=saved.started;
    actions=Object.fromEntries(Object.entries(saved.actions).filter(([id,at])=>Object.hasOwn(products,id)&&Number.isFinite(at)));
  }
} catch {}
function persist(){try{sessionStorage.setItem(stateKey,JSON.stringify({started,actions}));}catch{}}
persist();
const demoNow=()=>replayTime+Math.max(0,Date.now()-started);
const fmt=value=>value.toLocaleString('en-US');
const clockFormat=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Berlin',weekday:'short',hour:'2-digit',minute:'2-digit'});
const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const countOpen=()=>Object.keys(products).length-Object.keys(actions).length;
const currentView=()=>Object.hasOwn(views,location.hash.slice(1))?location.hash.slice(1):'overview';
const content=document.querySelector('#content'),dialog=document.querySelector('#dialog'),dialogContent=document.querySelector('#dialog-content');
const title=(name,heading,aside='')=>'<div class="card-heading"><h2 class="card-title">'+icon(name)+heading+'</h2>'+aside+'</div>';
function statCards(){
  const metrics=editions.map(e=>{
    const rate=e.median/e.target*100;
    return '<article class="stat edition '+e.cls+'"><h2 class="stat-label"><span class="chip-icon">'+icon(e.icon)+'</span>'+e.name+'</h2><div class="metric"><strong>'+fmt(e.target-e.median)+'</strong><span>boxes short</span></div><div class="progress-wrap"><div class="track" aria-hidden="true"><span style="width:'+rate+'%"></span></div><div class="progress-caption"><span>'+fmt(e.median)+' / '+fmt(e.target)+' expected</span><b>'+Math.round(rate)+'%</b></div></div></article>';
  }).join('');
  return '<section class="stats" aria-label="Launch countdown and expected box shortages"><article class="stat countdown"><canvas aria-hidden="true"></canvas><h2 class="stat-label"><span class="chip-icon">'+icon('timer')+'</span>Time to launch</h2><div class="clock-readout" role="timer" aria-label="Time remaining">'+['Hours','Min','Sec'].map((u,i)=>(i?'<em aria-hidden="true">:</em>':'')+'<div><b id="clock-'+i+'">00</b><small>'+u.toUpperCase()+'</small></div>').join('')+'</div><div class="cutoff">Sun, 22 Nov · 20:00 CET</div></article>'+metrics+'</section>';
}
function tick(){
  const left=Math.max(0,Math.ceil((cutoff-demoNow())/1000));
  [Math.floor(left/3600),Math.floor(left/60)%60,left%60].forEach((n,i)=>{const el=document.getElementById('clock-'+i);if(el)el.textContent=String(n).padStart(2,'0');});
}
function offerCard(){
  const p=products[selected];
  const tabs=Object.entries(products).map(([id,v])=>'<button role="tab" id="tab-'+id+'" aria-controls="product-panel" aria-selected="'+(selected===id)+'" tabindex="'+(selected===id?0:-1)+'" data-product="'+id+'">'+v.tab+'</button>').join('');
  const emails=p.offers.map(o=>{
    const e=emailEvidence[o.key];
    const initials=e.supplier.split(' ').slice(0,2).map(w=>w[0]).join('');
    return '<div class="offer-row"><span class="vendor-avatar" aria-hidden="true">'+initials+'</span><div class="offer-info"><strong>'+escapeHtml(e.supplier)+'</strong><span>'+o.detail+'</span></div><button class="email-button" data-mail="'+o.key+'" aria-label="Read supplier email from '+escapeHtml(e.supplier)+'" title="Read email">'+icon('mail')+'</button></div>';
  }).join('');
  return '<section class="card offers-card">'+title('inbox','Supplier offers','<span class="secondary">By product</span>')+'<div class="tabs" role="tablist" aria-label="Select product">'+tabs+'</div><div role="tabpanel" id="product-panel" aria-labelledby="tab-'+selected+'"><article class="recommend"><div class="rec-top"><div class="rec-label">'+icon('spark')+'Recommended choice</div><span class="rec-due">'+icon('clock')+p.due+'</span></div><h3>'+p.title+'</h3><p>'+p.why+'</p><div class="rec-bottom"><div class="rec-cost"><b>'+p.value+'</b><small>'+p.valueLabel+'</small></div>'+actionButton(selected)+'</div></article><div class="offers-heading"><b>Supplier emails</b><small>'+p.offers.length+(p.offers.length===1?' thread':' threads')+'</small></div>'+emails+'</div></section>';
}
function actionButton(id){
  const p=products[id],done=!!actions[id];
  return '<button class="btn'+(done?' done':'')+'" '+(done?'disabled':'data-approve="'+id+'"')+'>'+icon('check')+(done?p.done:p.button)+'</button>';
}
function deadlineCard(full=false){
  const ids=full?orderedTasks:orderedTasks.filter(id=>!actions[id]);
  return '<section class="card">'+title('clock','Decision deadlines','<span class="small-count" aria-label="'+countOpen()+' open decisions">'+countOpen()+'</span>')+'<div class="deadline-list">'+ids.map(id=>{
    const p=products[id];
    return '<button class="deadline-item" data-task="'+id+'"><span class="deadline-icon '+p.tone+'">'+icon(actions[id]?'check':p.icon)+'</span><span class="deadline-copy"><b>'+p.queue+'</b><small>'+(full?p.owner+' · ':'')+p.short+'</small></span><span class="due'+(actions[id]?' done':'')+'">'+(actions[id]?'Logged':p.due)+'</span></button>';
  }).join('')+(ids.length?'':'<p class="empty">All four actions are logged. Follow up with the assigned teams.</p>')+'</div></section>';
}
function insightCard(){
  return '<section class="card insight">'+title('bulb','Actionable insight')+'<h3>Protect Collector’s boxes first</h3><p>Each missed preorder means a €120 refund. Allocate scarce game cards to Collector’s first and pair the art-book hold with a statue inspection.</p></section>';
}
function activityCard(){
  const entries=Object.entries(actions).sort((a,b)=>b[1]-a[1]);
  return '<section class="card">'+title('history','Decision history','<span class="small-count">'+entries.length+'</span>')+(entries.length?entries.map(([id,at])=>'<div class="audit-item"><span class="deadline-icon">'+icon('check')+'</span><div><strong>'+products[id].done+'</strong><p>'+products[id].tab+' · '+clockFormat.format(at)+' CET · Simulated</p></div><button class="outline-btn audit-actions" data-undo="'+id+'" aria-label="Undo '+products[id].done+'">Undo</button></div>').join(''):'<p class="empty">Your first approval or assigned action will appear here.</p>')+'</section>';
}
function overview(){
  return statCards()+'<div class="body-grid">'+offerCard()+'<div class="side-stack">'+deadlineCard()+insightCard()+'</div></div><footer class="forecast-foot"><span>'+icon('history')+'Replay starts Sat 21 Nov at 20:02 CET</span><button class="quiet" data-forecast>'+icon('info')+'Forecast details</button></footer>';
}
function render(){
  const view=currentView();
  document.querySelector('#view-title').textContent=views[view][0];
  document.querySelector('#view-subtitle').textContent=views[view][1];
  document.querySelector('#nav-count').textContent=countOpen();
  document.querySelectorAll('[data-nav]').forEach(a=>{
    if(a.dataset.nav===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
    a.setAttribute('aria-label',views[a.dataset.nav][0]);
  });
  document.title=views[view][0]+' · Lio Launch Desk';
  content.innerHTML=view==='overview'?overview():'<div class="focused">'+({offers:offerCard,decisions:()=>deadlineCard(true),activity:activityCard})[view]()+'</div>';
  tick();drawLaunchCargo(content.querySelector('canvas'));
}
function selectProduct(id,focus=false){
  selected=id;const card=content.querySelector('.offers-card');card.outerHTML=offerCard();if(focus)document.getElementById('tab-'+id).focus();
}
function fields(items){return '<dl>'+items.map(([a,b])=>'<dt>'+a+'</dt><dd>'+b+'</dd>').join('')+'</dl>';}
function openDialog(contentHtml){
  dialogContent.innerHTML=contentHtml;
  dialog.setAttribute('aria-labelledby','dialog-title');
  if(!dialog.open)dialog.showModal();
}
function actionDialog(id){
  const p=products[id];
  openDialog('<div class="overline">'+p.tab+' · Demo decision</div><h2 id="dialog-title">'+p.title+'</h2><p class="modal-p">'+p.scope+'</p>'+fields([['Owner',p.owner],['Decision window',p.timing],['At stake',p.value+' · '+p.valueLabel]])+'<p class="mini">'+icon('info')+'Demo actions are recorded in this browser.</p><div class="dialog-actions"><button class="outline-btn" data-close>Close</button>'+(actions[id]?'<span class="tag green">'+p.done+'</span>':'<button class="btn" data-confirm="'+id+'">'+icon('check')+p.button+'</button>')+'</div>');
}
function emailDialog(key){
  const o=Object.values(products).flatMap(p=>p.offers).find(item=>item.key===key),e=emailEvidence[key];
  openDialog('<div class="overline">Supplier email</div><h2 id="dialog-title">'+escapeHtml(e.supplier)+'</h2><p class="mini">'+icon('mail')+'Sat, 21 Nov · '+e.time+' CET</p><div class="mail-summary">'+o.summary+'</div><details class="original"><summary>Original email excerpt</summary><p>'+escapeHtml(e.excerpt)+'</p></details>'+fields([['Subject',escapeHtml(e.subject)],['Thread',e.thread]])+'<div class="dialog-actions"><button class="outline-btn" data-close>Close</button></div>');
}
function forecastDialog(){
  openDialog('<div class="overline">Forecast details</div><h2 id="dialog-title">Expected boxes at launch</h2><p class="modal-p">The dashboard uses the median result from 500 packing simulations with Collector’s Edition first. Short boxes are the difference between the launch target and that median.</p>'+fields(editions.map(e=>[e.name,fmt(e.target)+' target − '+fmt(e.median)+' expected = <b>'+fmt(e.target-e.median)+' short</b>']))+'<p class="modal-p">Forecast snapshot · Sat 21 Nov, 19:25 CET. Supplier emails through 20:02 CET. A reservation alone does not change the forecast. Arrival and quality release still matter.</p><div class="dialog-actions"><button class="outline-btn" data-close>Close</button></div>');
}
document.addEventListener('click',event=>{
  const btn=event.target.closest('button');
  if(!btn)return;
  const d=btn.dataset;
  if('close' in d){dialog.close();return;}
  if(d.product){selectProduct(d.product,true);return;}
  if(d.mail){emailDialog(d.mail);return;}
  if(d.approve||d.task){actionDialog(d.approve||d.task);return;}
  if('forecast' in d){forecastDialog();return;}
  if(d.confirm&&!actions[d.confirm]){
    actions[d.confirm]=demoNow();persist();dialog.close();render();notify(products[d.confirm].done+'. Saved to activity log.');
    const nextFocus=content.querySelector('[data-approve], .btn.done')?.closest('article')?.querySelector('h3')??document.querySelector('#view-title');
    nextFocus.setAttribute('tabindex','-1');
    nextFocus.focus({preventScroll:true});
  }
  if(d.undo){
    delete actions[d.undo];persist();render();notify('Decision undone. The action is open again.');
    (content.querySelector('[data-undo]')??document.querySelector('#main')).focus({preventScroll:true});
  }
});
function notify(message){
  document.querySelector('#announcer').textContent=message;
  let toast=document.querySelector('#toast');if(!toast){toast=document.createElement('div');toast.id='toast';toast.ariaHidden='true';document.body.appendChild(toast);}
  toast.textContent=message;toast.hidden=false;clearTimeout(notify.timeout);notify.timeout=setTimeout(()=>toast.hidden=true,3500);
}
dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
document.addEventListener('keydown',event=>{
  const tab=event.target.closest('[role=tab]');if(!tab)return;
  const keys=Object.keys(products),index=keys.indexOf(selected);
  const next={ArrowLeft:(index+keys.length-1)%keys.length,ArrowRight:(index+1)%keys.length,Home:0,End:keys.length-1}[event.key];
  if(next!==undefined){event.preventDefault();selectProduct(keys[next],true);}
});
window.addEventListener('hashchange',()=>{if(dialog.open)dialog.close();render();window.scrollTo(0,0);document.querySelector('#main').focus({preventScroll:true});});
window.addEventListener('resize',()=>drawLaunchCargo(content.querySelector('canvas')));
render();setInterval(tick,1000);
