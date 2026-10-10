'use strict';
const $ = id => document.getElementById(id);
const icons = {
  devices:'<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M8 21h8M12 15v6"/>',
  activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  settings:'<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1M5.6 18.4l2.1-2.1m8.6-8.6 2.1-2.1"/><circle cx="12" cy="12" r="5"/>',
  scan:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  unknown:'<circle cx="12" cy="12" r="8"/><path d="M10 9a2 2 0 1 1 3 2l-1 1v1m0 3h.01"/>',
  download:'<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
  shield:'<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9h.01"/>',
  router:'<rect x="3" y="11" width="18" height="8" rx="2"/><path d="M7 11V4m10 7V4M7 15h.01M11 15h.01"/>',
  server:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 9h14M5 15h14M9 6h.01M9 12h.01M9 18h.01"/>',
  phone:'<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.devices}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => {el.innerHTML=icon(el.dataset.icon);});
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let state=null, filter='all', sort='ip', descending=false, selectedId=null, requesting=false, scanRequested=false, toastTimer;
const date = value => value ? new Date(value).toLocaleString('de-DE',{dateStyle:'short',timeStyle:'short'}) : '–';
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},3500);}
async function api(path,method='GET',body){
  const response = await fetch(path,{method,headers:body ? {'Content-Type':'application/json'} : {},body:body ? JSON.stringify(body) : undefined});
  if(!response.ok){let result;try{result=await response.json();}catch{result={};}throw new Error(result.error || `Anfrage fehlgeschlagen (${response.status}).`);}
  return response.json();
}
function visibleDevices(){
  const q=$('search').value.toLocaleLowerCase(), status=$('status-filter').value;
  return state.devices.filter(d => (filter==='all'||(filter==='known'?d.known:!d.known)) && (status==='all'||(status==='online'?d.online:!d.online)) && [d.name,d.description,d.ip,d.mac,d.vendor,d.interface].some(v=>v.toLocaleLowerCase().includes(q)))
    .sort((a,b)=>{let n=sort==='ip' ? a.ip.split('.').reduce((n,v)=>n*256+Number(v),0)-b.ip.split('.').reduce((n,v)=>n*256+Number(v),0) : (a.name||a.vendor||a.mac).localeCompare(b.name||b.vendor||b.mac,'de');return descending?-n:n;});
}
function deviceIcon(d){const text=(d.name+' '+d.vendor).toLowerCase();if(/router|fritz|access point|ubiquiti/.test(text))return 'router';if(/nas|diskstation|synology|assistant|raspberry/.test(text))return 'server';if(/iphone|phone/.test(text))return 'phone';return 'devices';}
function renderDevices(){
  if(!state)return;
  const devices=visibleDevices();
  $('devices-body').innerHTML=devices.map(d=>`<tr><td><div class="device-cell"><span class="device-icon">${icon(deviceIcon(d))}</span><div><button class="device-title" data-detail="${d.id}">${escapeHtml(d.name || d.vendor || 'Unbenanntes Gerät')}</button><div class="device-desc">${escapeHtml(d.description || (d.known ? d.vendor : 'Noch nicht zugeordnet'))}</div></div></div></td><td class="mono">${escapeHtml(d.ip)}</td><td class="mono mac">${escapeHtml(d.mac)}</td><td><span class="status ${d.online?'':'offline'}"><span class="dot green"></span>${d.online?'Online':'Offline'}</span></td><td><button class="known-badge ${d.known?'':'unknown'}" data-known="${d.id}" aria-label="${d.known?'Known-Markierung entfernen':'Als Known markieren'}: ${escapeHtml(d.name||d.ip)}">${icon(d.known?'check':'unknown')}${d.known?'Known':'Unbekannt'}</button></td><td><button class="row-detail" data-detail="${d.id}" aria-label="Details zu ${escapeHtml(d.name||d.ip)}">↗</button></td></tr>`).join('');
  $('empty-state').hidden=devices.length>0;
  $('empty-state').querySelector('h3').textContent=state.devices.length?'Keine passenden Geräte':'Noch keine Geräte';
  $('empty-state').querySelector('p').textContent=state.devices.length?'Ändere die Suche oder deine Filter.':'Starte einen Scan, um dein Netzwerk kennenzulernen.';
  $('result-count').textContent=`${devices.length} von ${state.devices.length} Geräten`;
}
function render(){
  const d=state.devices,known=d.filter(d=>d.known).length,online=d.filter(d=>d.online).length,unknown=d.length-known;
  for(const [id,val] of Object.entries({'stat-total':d.length,'stat-online':online,'stat-known':known,'stat-unknown':unknown,'nav-count':d.length,'inventory-count':d.length,'tab-total':d.length,'tab-known':known,'tab-unknown':unknown}))$(id).textContent=val;
  $('unknown-note').textContent=unknown ? 'Zeit, sie kennenzulernen' : 'Alle Geräte sind zugeordnet';
  $('demo-banner').hidden=!state.config.demo;
  $('mode').textContent=state.config.demo?'DEMO':'LIVE · LOKAL';
  const successful=state.scans.find(s=>s.status==='success'),latest=state.scans[0];
  $('last-scan').textContent=successful?`Letzter Scan: ${date(successful.finished_at)}`:'Noch kein erfolgreicher Scan';
  if(latest?.status==='error'){$('connection-error').hidden=false;$('connection-error').textContent='Scan fehlgeschlagen: '+latest.error;}
  else $('connection-error').hidden=true;
  for(const id of ['scan-button','history-scan']){const b=$(id);b.disabled=state.scanning||scanRequested;b.classList.toggle('scanning',state.scanning);b.innerHTML=icon('scan')+`<span>${state.scanning?'Scan läuft …':state.config.demo?'Demo-Scan starten':'Netzwerk scannen'}</span>`;}
  renderDevices();
  $('scans-body').innerHTML=state.scans.map(s=>`<tr><td>${date(s.started_at)}</td><td><span class="status ${s.status==='error'?'error':s.status==='running'?'offline':''}">${s.status==='success'?'Erfolgreich':s.status==='error'?'Fehlgeschlagen':'Läuft …'}</span></td><td>${s.status==='success'?s.found:'–'}</td><td>${escapeHtml(s.error|| (s.finished_at?'Abgeschlossen: '+date(s.finished_at):'Scan wird ausgeführt'))}</td></tr>`).join('');
  $('no-scans').hidden=state.scans.length>0;
  $('config-details').innerHTML=`<dt>Modus</dt><dd>${state.config.demo?'Demo mit Beispieldaten':'Live · ARP-Scan'}</dd><dt>Interfaces</dt><dd>${escapeHtml(state.config.interfaces.join(', ')||'Nicht konfiguriert')}</dd><dt>Scan-Intervall</dt><dd>${state.config.interval} Sekunden</dd><dt>Speicherung</dt><dd>SQLite · Persistentes Datenvolume</dd><dt>Nächster Scan</dt><dd>${state.scanning?'Scan läuft':state.next_scan?date(state.next_scan*1000):'–'}</dd>`;
}
async function refresh(){
  if(requesting)return;requesting=true;
  try{state=await api('/api/state');render();}catch(e){$('connection-error').textContent=e.message;$('connection-error').hidden=false;$('mode').textContent='VERBINDUNG FEHLT';}
  finally{requesting=false;}
}
async function scan(){
  scanRequested=true;render();
  try{await api('/api/scan','POST',{});toast(state.config.demo?'Demo-Scan gestartet.':'Netzwerk-Scan gestartet.');}catch(e){toast(e.message);}
  finally{scanRequested=false;await refresh();}
}
function openDevice(id){
  const d=state.devices.find(d=>d.id===id);if(!d)return;selectedId=id;
  $('dialog-title').textContent=d.name||d.vendor||'Unbenanntes Gerät';
  $('device-name').value=d.name;$('device-description').value=d.description;$('device-known').checked=d.known;$('form-error').hidden=true;
  $('device-meta').innerHTML=[['IP-Adresse',d.ip],['MAC-Adresse',d.mac],['Hersteller',d.vendor||'Unbekannt'],['Interface',d.interface],['Zuerst gesehen',date(d.first_seen)],['Zuletzt gesehen',date(d.last_seen)]].map(([k,v])=>`<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join('');
  $('device-dialog').showModal();
}
$('devices-body').addEventListener('click',async e=>{
  const detail=e.target.closest('[data-detail]');if(detail){openDevice(Number(detail.dataset.detail));return;}
  const button=e.target.closest('[data-known]');if(!button)return;
  const d=state.devices.find(d=>d.id===Number(button.dataset.known));button.disabled=true;
  try{await api(`/api/devices/${d.id}`,'PATCH',{known:!d.known});toast(d.known?'Known-Markierung entfernt.':'Gerät als Known markiert.');await refresh();}catch(e){button.disabled=false;toast(e.message);}
});
$('device-form').addEventListener('submit',async e=>{
  e.preventDefault();$('save-button').disabled=true;$('form-error').hidden=true;
  try{await api(`/api/devices/${selectedId}`,'PATCH',{name:$('device-name').value.trim(),description:$('device-description').value.trim(),known:$('device-known').checked});$('device-dialog').close();toast('Gerät gespeichert.');await refresh();}
  catch(e){$('form-error').textContent=e.message;$('form-error').hidden=false;}
  finally{$('save-button').disabled=false;}
});
for(const id of ['dialog-close','dialog-cancel'])$(id).addEventListener('click',()=>$('device-dialog').close());
for(const id of ['scan-button','history-scan'])$(id).addEventListener('click',scan);
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==`page-${b.dataset.page}`);document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('active',n===b));$('page-label').textContent=b.textContent.replace(/\d+$/,'').trim();}));
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(t=>t.classList.toggle('active',t===b));renderDevices();}));
$('search').addEventListener('input',renderDevices);$('status-filter').addEventListener('change',renderDevices);
for(const field of ['name','ip'])$('sort-'+field).addEventListener('click',()=>{descending=sort===field?!descending:false;sort=field;renderDevices();});
$('export-button').addEventListener('click',()=>{
  if(!state)return;
  const cell=v=>'"'+String(v??'').replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';
  const lines=[['Name','Beschreibung','IP','MAC','Hersteller','Interface','Known','Online','Zuerst gesehen','Zuletzt gesehen'],...visibleDevices().map(d=>[d.name,d.description,d.ip,d.mac,d.vendor,d.interface,d.known,d.online,d.first_seen,d.last_seen])];
  const url=URL.createObjectURL(new Blob(['\ufeff'+lines.map(r=>r.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='lanytic-geraete.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Gefilterte Geräteliste exportiert.');
});
refresh();setInterval(refresh,2500);
