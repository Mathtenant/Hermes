"""Static CSS/JS assets for the HERMES dashboard HTML export.

These constants are consumed by ``dashboard_html.render_html`` via a
``string.Template`` that uses the ``@@`` delimiter, so ``$`` and ``{}``
characters in the CSS/JS below are treated literally and need no escaping.
"""

_CSS = r""":root{--bg:#fafafa;--fg:#1a1a1a;--border:#ddd;--accent:#1976d2;--ok:#2e7d32;--warn:#b58900;--late:#c62828;--card:#fff;--th:#f0f0f0}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
.topbar{position:sticky;top:0;z-index:99;background:var(--bg);border-bottom:1px solid var(--border);padding:.5rem 1rem;display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
.topbar h1{font-size:1.05rem;font-weight:700}
.scope{font-weight:600;color:var(--accent)}
.range{font-size:.85rem;color:#666}
nav a{text-decoration:none;color:var(--accent);font-size:.9rem}
#theme-toggle{margin-left:auto;padding:.25rem .6rem;cursor:pointer;border:1px solid var(--border);border-radius:4px;background:var(--card);color:var(--fg)}
main{padding:1rem 1.5rem;max-width:1400px;margin:0 auto}
section{margin-bottom:2rem}
section>h2{font-size:.95rem;font-weight:700;margin-bottom:.6rem;padding-bottom:.2rem;border-bottom:2px solid var(--accent);text-transform:uppercase;letter-spacing:.04em}
.tl-list{list-style:none;display:flex;flex-direction:column;gap:.3rem}
.tl-item{display:flex;align-items:baseline;gap:.6rem;font-size:.88rem}
.tl-date{width:6.5rem;flex-shrink:0;color:#777;font-variant-numeric:tabular-nums}
.tl-dot{width:.55rem;height:.55rem;border-radius:50%;flex-shrink:0;margin-top:.4rem}
.tl-dot.closed{background:var(--ok)}.tl-dot.open{background:var(--warn)}.tl-dot.blocked{background:var(--late)}.tl-dot.future{background:#bbb}
.kanban-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
@media(max-width:700px){.kanban-grid{grid-template-columns:1fr}}
.k-col{border:1px solid var(--border);border-radius:6px;overflow:hidden;background:var(--card)}
.k-hdr{padding:.45rem .7rem;font-size:.82rem;font-weight:700;background:var(--th);border-bottom:1px solid var(--border)}
.k-card{padding:.45rem .7rem;border-bottom:1px solid var(--border);font-size:.83rem}
.k-card:last-child{border-bottom:none}
.k-meta{font-size:.75rem;color:#888;margin-top:.1rem}
.filters{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.5rem;align-items:center}
.filters select,.filters button{padding:.2rem .5rem;border:1px solid var(--border);border-radius:4px;background:var(--card);color:var(--fg);cursor:pointer;font-size:.83rem}
.tbl-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.865rem}
th{background:var(--th);text-align:left;padding:.35rem .55rem;white-space:nowrap}
th button{background:none;border:none;cursor:pointer;font:inherit;font-weight:700;padding:0;color:inherit;width:100%;text-align:left}
td{padding:.3rem .55rem;border-bottom:1px solid var(--border);vertical-align:top}
tr.hidden{display:none}
tr:hover td{background:color-mix(in srgb,var(--accent) 4%,transparent)}
.prio-blocker>td:first-child{border-left:3px solid var(--late)}
.prio-high>td:first-child{border-left:3px solid var(--warn)}
#wbs details{padding:.15rem 0 .15rem .9rem;border-left:2px solid var(--border);margin:.15rem 0}
#wbs summary{cursor:pointer;list-style:none;display:flex;gap:.5rem;align-items:baseline;font-size:.875rem}
#wbs summary::-webkit-details-marker{display:none}
#wbs summary::before{content:"▶";font-size:.55rem;color:#888;transition:transform .12s;flex-shrink:0;margin-top:.35rem}
#wbs details[open]>summary::before{transform:rotate(90deg)}
.wbs-num{color:#999;font-variant-numeric:tabular-nums;min-width:3rem;flex-shrink:0}
.wbs-leaf{padding:.15rem 0 .15rem .9rem;font-size:.875rem;display:flex;gap:.5rem}
.wbs-btn{display:flex;gap:.5rem;margin-bottom:.4rem}
.wbs-btn button{font-size:.8rem;padding:.15rem .45rem;border:1px solid var(--border);border-radius:3px;background:var(--card);color:var(--fg);cursor:pointer}
small.meta{color:#888;font-size:.78rem}
.badge{display:inline-block;padding:.05rem .35rem;border-radius:3px;font-size:.75rem;font-weight:600;line-height:1.4}
.v-pass{color:var(--ok)}.v-partial{color:var(--warn)}.v-fail{color:var(--late)}
footer{text-align:center;font-size:.78rem;color:#aaa;padding:.75rem;border-top:1px solid var(--border);margin-top:1rem}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121212;--fg:#e0e0e0;--border:#333;--card:#1e1e1e;--th:#252525}}
[data-theme=dark]{--bg:#121212;--fg:#e0e0e0;--border:#333;--card:#1e1e1e;--th:#252525}
@media print{.filters,#theme-toggle,nav,.wbs-btn{display:none}body{font-size:10.5pt}.topbar{position:static;border:none}table{page-break-inside:auto}tr{page-break-inside:avoid}}
.panel-body{overflow:hidden;transition:max-height .3s ease;max-height:500px}
.panel-body.is-collapsed{max-height:0}
.section-toggle{background:none;border:none;cursor:pointer;font-size:.9rem;color:#999;margin-left:.4rem;vertical-align:middle;line-height:1}
"""

_JS = r"""'use strict';
(function(){
function toggleTheme(){
  var h=document.documentElement,t=h.getAttribute('data-theme')==='dark'?'light':'dark';
  h.setAttribute('data-theme',t);
  try{localStorage.setItem('hermes-theme',t);}catch(e){}
  var b=document.getElementById('theme-toggle');
  if(b){b.textContent=t==='dark'?'Light':'Dark';b.setAttribute('aria-pressed',String(t==='dark'));}
}
function sortTable(th){
  var tbl=th.closest('table'),tbody=tbl.querySelector('tbody');
  var idx=Array.from(th.parentNode.cells).indexOf(th.closest('th'));
  var asc=th.dataset.sortDir!=='asc';th.dataset.sortDir=asc?'asc':'desc';
  var rows=Array.from(tbody.rows);
  rows.sort(function(a,b){
    var av=a.cells[idx]?a.cells[idx].textContent.trim():'';
    var bv=b.cells[idx]?b.cells[idx].textContent.trim():'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)){return asc?an-bn:bn-an;}
    return asc?av.localeCompare(bv):bv.localeCompare(av);
  });
  rows.forEach(function(r){tbody.appendChild(r);});
}
function applyFilters(tblId){
  var wrap=document.getElementById(tblId);if(!wrap)return;
  var prev=wrap.previousElementSibling;
  var sels=prev?prev.querySelectorAll('[data-filter-col]'):[];
  var filters=Array.from(sels).map(function(s){return{col:+s.dataset.filterCol,val:s.value};});
  Array.from(wrap.querySelectorAll('tbody tr')).forEach(function(row){
    var show=filters.every(function(f){return !f.val||(row.cells[f.col]&&row.cells[f.col].textContent.trim()===f.val);});
    row.classList.toggle('hidden',!show);
  });
}
function exportTableCSV(tblId){
  var tbl=document.getElementById(tblId);if(!tbl)return;
  var rows=Array.from(tbl.querySelectorAll('tr')).filter(function(r){return !r.classList.contains('hidden');});
  var csv=rows.map(function(r){return Array.from(r.cells).map(function(c){return '"'+c.textContent.trim().replace(/"/g,'""')+'"';}).join(',');}).join('\n');
  var url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  var a=document.createElement('a');a.href=url;a.download=tblId+'.csv';a.click();
  setTimeout(function(){URL.revokeObjectURL(url);},1000);
}
function setAllDetails(open){document.querySelectorAll('#wbs details').forEach(function(d){d.open=open;});}
var _snap=[];
window.onbeforeprint=function(){_snap=Array.from(document.querySelectorAll('#wbs details')).map(function(d){return d.open;});setAllDetails(true);};
window.onafterprint=function(){Array.from(document.querySelectorAll('#wbs details')).forEach(function(d,i){d.open=!!_snap[i];});};
try{var _t=localStorage.getItem('hermes-theme');if(_t)document.documentElement.setAttribute('data-theme',_t);}catch(e){}
document.querySelectorAll('th button[data-sort-col]').forEach(function(b){b.addEventListener('click',function(){sortTable(b.closest('th'));});});
var _tog=document.getElementById('theme-toggle');if(_tog)_tog.addEventListener('click',toggleTheme);
// Q2 — collapse panels via event delegation on [data-collapse-target].
document.addEventListener('click',function(e){
  var btn=e.target.closest&&e.target.closest('[data-collapse-target]');
  if(!btn)return;
  var targetId=btn.dataset.collapseTarget;
  var panel=document.getElementById(targetId);
  if(!panel)return;
  var collapsed=panel.classList.toggle('is-collapsed');
  btn.textContent=collapsed?'+':'−';
  btn.setAttribute('aria-expanded',String(!collapsed));
  try{sessionStorage.setItem('panel-collapsed-'+targetId,String(collapsed));}catch(ex){}
});
// Restore panel collapse state from sessionStorage.
(function(){
  var btns=document.querySelectorAll('[data-collapse-target]');
  for(var i=0;i<btns.length;i++){
    var b=btns[i];var tid=b.dataset.collapseTarget;
    if(sessionStorage.getItem('panel-collapsed-'+tid)==='true'){
      var p=document.getElementById(tid);
      if(p){p.classList.add('is-collapsed');b.textContent='+';b.setAttribute('aria-expanded','false');}
    }
  }
})();
})();
"""
