'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cache = new Map();
async function data(path) { if(!cache.has(path)) cache.set(path,fetch(`data/${path}.json`).then(r=>{if(!r.ok) throw Error(`Could not load ${path}. Try again.`);return r.json();}).catch(e=>{cache.delete(path);throw e;}));return cache.get(path); }
let catalog,index,actions,reviews,mode='search',page=0,hits=[],epoch=0,detailEpoch=0,routeEpoch=0;
const labels={operative:'Operative text',repealed:'Repealed',renumbered:'Renumbered',note_only:'Note only',series_membership:'Series membership',session_law_provision:'Session-law provision',incidental_repeal_reference:'Incidental repeal reference',unresolved:'Needs review'};
const fmt=n=>n.toLocaleString();
function source(url,label='Original PDF') { return /^https:\/\//.test(url||'') ? `<a class="source" href="${esc(url)}" target="_blank" rel="noopener">${label} ↗</a>`:''; }
function error(e,target='detail') { $(target).innerHTML=`<p class="error">${esc(e.message)} Reload the page to retry.</p>`; }
function words(q) {return [...new Set(q.toLowerCase().match(/[a-z0-9]+/g)||[])];}
async function search(){
  const current=++epoch;page=0;
  $('summary').textContent='Searching…';
  const q=$('query').value.trim(),chapter=$('chapter').value,filter=$('filter').value;
  let found=[];
  try {
    if(mode==='search'){
      let candidates=null;
      const exact=index.findIndex(r=>r[0].toLowerCase()===q.replace(/^ors\s+/i,'').toLowerCase());
      if(q && exact>=0) candidates=new Set([exact]);
      else if(q){
        const terms=words(q);
        for(const word of terms){
          const prefix=word.slice(0,2);
          const shard=catalog.search_shards.includes(prefix)?await data(`search/${prefix}`):{};
          const next=new Set(shard[word]||[]);
          candidates=candidates===null?next:new Set([...candidates].filter(id=>next.has(id)));
          if(!candidates.size)break;
        }
        if(!terms.length)candidates=new Set();
      }
      found=index.filter((r,i)=>(!candidates||candidates.has(i))&&(!chapter||r[1]===chapter)&&(!filter||r[3]===filter));
    }else if(mode==='changes'){
      found=actions.filter(a=>(!filter||a.action_type===filter)&&(!chapter||(a.affected_ors_section||'').split('.')[0]===chapter)&&(!q||words(q).every(w=>`${a.bill_number} ${a.affected_ors_section||''} ${a.session_law_chapter} ${a.session_law_section} ${a.condition_text||''}`.toLowerCase().includes(w))));
    }else{
      found=reviews.filter(r=>(!filter||r.disposition===filter)&&(!q||words(q).every(w=>`${r.text} ${r.category} ${r.clause}`.toLowerCase().includes(w))));
    }
    if(current!==epoch)return;
    hits=found;
    $('summary').textContent=`${fmt(hits.length)} ${mode==='search'?'sections':mode==='changes'?'actions':'clauses'}${q?' found':''}${mode==='search'&&q?' · Exact words, across printed versions.':''}`;
    renderResults();
  }catch(e){if(current===epoch)error(e,'result-list');}
}
function renderResults(){
  const selection=new URLSearchParams(location.hash.split('?')[1]||'').get('id');
  $('result-list').innerHTML=hits.slice(page*40,page*40+40).map(r=>{
    const id=mode==='search'?r[0]:r.id;
    let content;
    if(mode==='search')content=`<span class="number">ORS ${esc(r[0])}</span><strong>${esc(r[2]||'No printed catchline')}</strong><span class="meta">${esc(labels[r[3]]||r[3])}${r[4]>1?` · ${r[4]} printed versions`:''}</span>`;
    else if(mode==='changes')content=`<span class="number">${esc(r.action_type)} · ${esc(r.affected_ors_section?'ORS '+r.affected_ors_section:'Unassigned ORS number')}</span><strong>${esc(r.bill_number)} · § ${esc(r.session_law_section)}</strong><span class="meta">Oregon Laws ${r.session_year}, chapter ${r.session_law_chapter}${r.condition_text?' · Conditional':''}</span>`;
    else content=`<span class="number">${esc(labels[r.category]||r.category)}</span><strong>${esc(r.source_url.split('/').pop())} · § ${esc(r.clause)}</strong><span class="meta">${esc(r.text.slice(0,145))}…</span>`;
    return `<a class="result${id===selection?' selected':''}" href="#${mode}?id=${encodeURIComponent(id)}">${content}</a>`;
  }).join('')||'<p class="empty">No matches. Try fewer words or a different filter.</p>';
  $('pagination').innerHTML=hits.length?`<button class="secondary" id="prev" ${page===0?'disabled':''}>Previous</button><span>${page+1} / ${Math.ceil(hits.length/40)}</span><button class="secondary" id="next" ${(page+1)*40>=hits.length?'disabled':''}>Next</button>`:'';
  if($('prev'))$('prev').onclick=()=>{page--;renderResults();};
  if($('next'))$('next').onclick=()=>{page++;renderResults();};
}
function notesBlock(title,notes){return notes.length?`<details><summary>${title} (${notes.length})</summary>${notes.map(n=>`<p class="note">${esc(n.note_text)}</p>`).join('')}</details>`:'';}
async function sectionDetail(id){
  const current=++detailEpoch,row=index.find(r=>r[0]===id);
  if(!row)throw Error('Section not found in this edition.');
  $('detail').innerHTML='<p class="loading">Loading section…</p>';
  const chapter=catalog.chapters.find(c=>c.chapter_number===row[1]),chunk=await data(`chapters/${row[1]}`);
  if(current!==detailEpoch)return;
  const s=chunk.sections[id],related=actions.filter(a=>a.affected_ors_section===id);
  $('detail').innerHTML=`<div class="detail-top"><span class="eyebrow">ORS ${esc(id)}</span><span class="badge">2023 printed edition</span>${source(chapter.source_url)}</div><h2>${esc(row[2]||'Section '+id)}</h2><p class="note">Chapter ${esc(row[1])} · ${esc(chapter.title)}</p>${s.versions.length>1?'<div class="notice">Multiple texts appear in this edition. Printed order does not determine which version applies on a given date. Read the publication notes.</div>':''}<div class="version-controls"><div><label for="version">Printed version</label><select id="version">${s.versions.map((v,i)=>`<option value="${i}">Version ${i+1} · ${esc(labels[v.status]||v.status)}</option>`).join('')}</select></div>${s.versions.length>1?'<button class="secondary" id="compare">Compare versions</button>':''}</div><div id="version-text"></div>${notesBlock('Pending & publication change notes',s.pending)}${notesBlock('Publication notes & source credits',s.notes)}${notesBlock('Chapter notes',chunk.notes)}<h3>Linked session-law actions (${related.length})</h3>${related.map(a=>`<a class="result" href="#changes?id=${a.id}"><span class="number">${esc(a.action_type)} · ${esc(a.bill_number)}</span><strong>Chapter ${a.session_law_chapter}, § ${esc(a.session_law_section)}</strong><span class="meta">${a.condition_text?esc(a.condition_text):'2023 session law'}</span></a>`).join('')||'<p class="note">No direct action is linked in this dataset. This does not establish that the section is unchanged.</p>'}`;
  function version(v){return `<p class="badge">${esc(labels[v.status]||v.status)}</p><div class="text">${esc(v.content_text||'No body text printed.')}</div>${v.source_credit?`<p class="note">${esc(v.source_credit)}</p>`:''}${JSON.parse(v.publication_notes||'[]').map(t=>`<p class="notice">${esc(t)}</p>`).join('')}`;}
  $('version').onchange=()=>{$('version-text').innerHTML=version(s.versions[Number($('version').value)]);};$('version').onchange();
  if($('compare'))$('compare').onclick=()=>{
    const first=Number($('version').value),second=(first+1)%s.versions.length;
    $('version-text').innerHTML=`<div class="compare"><section><h3>Version ${first+1}</h3>${version(s.versions[first])}</section><section><label for="compare-version">Compare with</label><select id="compare-version">${s.versions.map((v,i)=>`<option value="${i}" ${i===second?'selected':''}>Version ${i+1}</option>`).join('')}</select><div id="compare-text">${version(s.versions[second])}</div></section></div>`;
    $('compare-version').onchange=()=>{$('compare-text').innerHTML=version(s.versions[Number($('compare-version').value)]);};
  };
}
async function actionDetail(id){
  const current=++detailEpoch;
  if(!actions.some(a=>a.id===id))throw Error('Action not found.');
  $('detail').innerHTML='<p class="loading">Loading action…</p>';
  const a=await data(`actions/${id}`);if(current!==detailEpoch)return;
  let text='',last=0;const chars=Array.from(a.raw_diff_text),slice=(a,b)=>chars.slice(a,b).join('');
  for(const t of a.tokens){text+=esc(slice(last,t.start));const tag=t.operation==='ADD'?'ins':t.operation==='DELETE'?'del':'span';text+=`<${tag}>${esc(slice(t.start,t.end))}</${tag}>`;last=t.end;}
  text+=esc(slice(last));
  $('detail').innerHTML=`<div class="detail-top"><span class="eyebrow">${esc(a.action_type)}</span><span class="badge">${esc(a.bill_number)}</span>${source(a.source_url)}</div><h2>${esc(a.affected_ors_section?'ORS '+a.affected_ors_section:'New provision · ORS number unassigned')}</h2><p class="note">Oregon Laws ${a.session_year}, chapter ${a.session_law_chapter}, section ${esc(a.session_law_section)}</p>${a.condition_text?`<div class="notice"><strong>Conditional instruction</strong><br>${esc(a.condition_text)}. The parser preserves this condition; it does not resolve whether it was satisfied.</div>`:''}<details><summary>Complete operative clause</summary><p class="note">${esc(a.operative_text)}</p></details><div class="legend"><ins>Addition</ins><del>Deletion</del><span>Plain text: retained</span></div><div class="text">${text}</div>${a.affected_ors_section&&index.some(r=>r[0]===a.affected_ors_section)?`<p><a href="#search?id=${encodeURIComponent(a.affected_ors_section)}">Read printed ORS ${esc(a.affected_ors_section)}</a></p>`:''}`;
}
function reviewDetail(id){
  ++detailEpoch;const r=reviews.find(r=>r.id===id);if(!r)throw Error('Review item not found.');
  $('detail').innerHTML=`<div class="detail-top"><span class="eyebrow">${esc(labels[r.category]||r.category)}</span>${source(r.source_url)}</div><h2>Section ${esc(r.clause)}</h2><div class="notice">${esc(r.explanation)}<br>Classification is rule-based and retains the original evidence.</div><p class="note">Parser diagnostic: ${esc(r.reason)}</p><div class="text">${esc(r.text)}</div>`;
}
async function route(){
  const current=++routeEpoch;++detailEpoch;
  const [view,query]=location.hash.slice(1).split('?'),next=['changes','review'].includes(view)?view:'search';
  const changed=next!==mode;mode=next;
  document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.dataset.view===mode);if(a.dataset.view===mode)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(changed){$('query').value='';$('chapter').value='';}
  $('heading').textContent=mode==='search'?'Search & browse':mode==='changes'?'Session-law changes':'Review queue';
  $('query').placeholder=mode==='search'?'e.g. 161.005 or housing assistance':mode==='changes'?'Bill, ORS number, or law chapter':'Search flagged clause text';
  document.querySelector('label[for="query"]').textContent=mode==='search'?'Find a section or search its text':mode==='changes'?'Find a session-law action':'Find a review item';
  $('chapter').parentElement.hidden=mode==='review';
  document.querySelector('label[for="filter"]').textContent=mode==='search'?'Printed status':mode==='changes'?'Action type':'Review disposition';
  if(changed)$('filter').innerHTML=mode==='search'?'<option value="">All statuses</option><option value="operative">Operative text</option><option value="repealed">Repealed</option><option value="renumbered">Renumbered</option><option value="note_only">Note only</option>':mode==='changes'?'<option value="">All actions</option><option>AMEND</option><option>REPEAL</option><option>ADD</option>':'<option value="">All clauses</option><option value="review_required">Needs review</option><option value="expected_scope">Expected scope exclusion</option>';
  const id=new URLSearchParams(query||'').get('id');
  try{await search();if(current!==routeEpoch)return;if(id){if(mode==='search')await sectionDetail(id);else if(mode==='changes')await actionDetail(id);else reviewDetail(id);if(matchMedia('(max-width:760px)').matches)$('detail').scrollIntoView({behavior:'smooth'});}}catch(e){if(current===routeEpoch)error(e);}
}
async function chapterDetail(){
  await search();if(mode!=='search'||!$('chapter').value)return;
  const current=++detailEpoch,number=$('chapter').value,c=catalog.chapters.find(c=>c.chapter_number===number);
  try{const chapter=await data(`chapters/${number}`);if(current!==detailEpoch)return;
  $('detail').innerHTML=`<div class="detail-top"><span class="eyebrow">Chapter ${esc(number)}</span>${source(c.source_url)}</div><h2>${esc(c.title)}</h2><p class="note">${fmt(c.section_count)} identified sections in the 2023 printed edition.</p>${chapter.notes.map(n=>`<div class="text">${esc(n.note_text)}</div>`).join('')}${notesBlock('Chapter change notices',chapter.pending||[])}<p class="note">Choose a result to read a section and its evidence.</p>`;}catch(e){error(e);}
}
async function start(){
  [catalog,index,actions,reviews]=await Promise.all(['catalog','index','actions','reviews'].map(data));
  $('chapter').innerHTML+='<option disabled>────────────</option>'+catalog.chapters.map(c=>`<option value="${esc(c.chapter_number)}">${esc(c.chapter_number)} · ${esc(c.title||'Untitled chapter')}</option>`).join('');
  $('review-count').textContent=fmt(catalog.unresolved);
  $('metrics').innerHTML=[[catalog.sections,'sections'],[catalog.chapters.length,'chapters'],[catalog.amendments,'actions']].map(([n,label])=>`<div><strong>${fmt(n)}</strong><span>${label}</span></div>`).join('');
  $('integrity').textContent=`Dataset SHA-256 ${catalog.database_sha256.slice(0,12)}…`;
  $('search-form').onsubmit=e=>{e.preventDefault();search();};$('chapter').onchange=chapterDetail;$('filter').onchange=search;
  window.addEventListener('hashchange',route);await route();
  if(document.modelContext?.registerTool){
    const lifecycle=new AbortController();window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
    try{await document.modelContext.registerTool({name:'search_ors_sections',title:'Search the 2023 ORS edition',description:'Search exact words across printed section versions and update visible results. Does not establish current legal effect.',inputSchema:{type:'object',properties:{query:{type:'string',maxLength:300}},required:['query'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:true},execute:async input=>{if(!input||typeof input.query!=='string'||input.query.length>300||Object.keys(input).some(k=>k!=='query'))throw Error('A query of at most 300 characters is required.');if(mode!=='search'){history.replaceState(null,'','#search');await route();}$('query').value=input.query;await search();return {edition:2023,total:hits.length,sections:hits.slice(0,20).map(r=>({ors_section:r[0],catchline:r[2],printed_status:r[3]}))};}},{signal:lifecycle.signal});}catch(e){console.warn('Optional agent search unavailable',e.message);}
  }
}
start().catch(e=>error(e,'result-list'));
